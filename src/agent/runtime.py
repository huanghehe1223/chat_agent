"""Agent runtime loop."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo
from uuid import uuid4

from src.agent.config import AgentConfig, load_config
from src.agent.llm import DeepSeekClient
from src.agent.memory import SessionMemoryStore, build_llm_context
from src.agent.schemas import AssistantMessage
from src.agent.trace import TraceLogger
from src.tools.registry import ToolRegistry, build_default_registry


StreamEventHandler = Callable[[dict[str, Any]], None]


class StreamingLLMClient(Protocol):
    def stream_chat_events(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ):
        """Yield parsed LLM stream events."""


@dataclass
class AgentTurnResult:
    session_id: str
    turn_id: str
    answer: str
    reasoning_content: str = ""
    steps: int = 0
    tool_executions: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)


class AgentRuntimeError(RuntimeError):
    """Raised when the agent loop cannot complete a turn."""


class AgentRuntime:
    """Small streaming agent loop for DeepSeek native tool calls."""

    DEFAULT_SYSTEM_PROMPT = (
        "你是一个简洁可靠的本地工具 Agent。"
        "需要计算、搜索或管理任务时调用可用工具；"
        "工具返回结果后，基于结果给出用户可见的简洁回答。"
        "不要把 reasoning_content 当作正式回答输出。"
    )
    DEFAULT_TIMEZONE = "Asia/Shanghai"

    def __init__(
        self,
        config: AgentConfig | None = None,
        llm_client: StreamingLLMClient | None = None,
        memory_store: SessionMemoryStore | None = None,
        registry: ToolRegistry | None = None,
        trace_logger: TraceLogger | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self.config = config or load_config()
        self.llm_client = llm_client or DeepSeekClient(self.config)
        self.memory_store = memory_store or SessionMemoryStore()
        self.registry = registry or build_default_registry(self.config)
        self.trace_logger = trace_logger or TraceLogger()
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT

    def run_turn(
        self,
        user_input: str,
        session_id: str = "default",
        on_event: StreamEventHandler | None = None,
    ) -> AgentTurnResult:
        """Run one user turn, executing tools until a final answer is produced."""

        session_id = resolve_session_id(session_id)
        turn_id = uuid4().hex[:12]
        self.memory_store.append_user_message(session_id, user_input)
        tool_executions: list[dict[str, Any]] = []
        last_reasoning = ""

        for step in range(1, self.config.max_agent_steps + 1):
            session = self.memory_store.load(session_id)
            messages = build_llm_context(session, system_prompt=self._system_prompt_with_runtime_context())
            tools = self.registry.to_openai_tools()
            message, events = self._stream_once(
                session_id=session_id,
                turn_id=turn_id,
                step=step,
                messages=messages,
                tools=tools,
                on_event=on_event,
            )
            assistant_message = AssistantMessage.from_api_message(message)
            last_reasoning = assistant_message.reasoning_content
            self.memory_store.append_assistant_message(session_id, assistant_message)

            if not assistant_message.tool_calls:
                return AgentTurnResult(
                    session_id=session_id,
                    turn_id=turn_id,
                    answer=assistant_message.content,
                    reasoning_content=assistant_message.reasoning_content,
                    steps=step,
                    tool_executions=tool_executions,
                    messages=self.memory_store.load(session_id)["messages"],
                )

            for tool_call in assistant_message.tool_calls:
                execution = self._execute_tool_call(tool_call)
                execution.update(
                    {
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "step": step,
                    }
                )
                tool_executions.append(execution)
                trace_record = self.trace_logger.record_tool_call(
                    session_id=session_id,
                    turn_id=turn_id,
                    step=step,
                    tool_call=tool_call,
                    execution=execution,
                )
                if on_event:
                    on_event({"type": "tool_result", "execution": execution, "trace": trace_record})
                if execution.get("tool") == "manage_todo_list" and "todoList" in execution.get("result", {}):
                    self.memory_store.set_todo_list(session_id, execution["result"]["todoList"])
                    if on_event:
                        on_event(
                            {
                                "type": "task_list",
                                "todoList": self.memory_store.get_todo_list(session_id),
                                "execution": execution,
                            }
                        )
                self.memory_store.append_tool_message(
                    session_id=session_id,
                    tool_call_id=execution.get("tool_call_id", ""),
                    name=execution.get("tool", "unknown"),
                    result=execution.get("result", {"error": execution.get("error", "unknown error")}),
                )

        fallback = "已达到本轮最大工具调用步数限制，暂时无法继续完成。"
        self.memory_store.append_assistant_message(
            session_id,
            AssistantMessage(role="assistant", content=fallback, reasoning_content=last_reasoning),
        )
        return AgentTurnResult(
            session_id=session_id,
            turn_id=turn_id,
            answer=fallback,
            reasoning_content=last_reasoning,
            steps=self.config.max_agent_steps,
            tool_executions=tool_executions,
            messages=self.memory_store.load(session_id)["messages"],
        )

    def _stream_once(
        self,
        session_id: str,
        turn_id: str,
        step: int,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_event: StreamEventHandler | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        events: list[dict[str, Any]] = []
        final_message: dict[str, Any] | None = None
        request = {
            "model": self.config.deepseek_model,
            "base_url": self.config.deepseek_base_url,
            "api_key": _mask_secret(self.config.deepseek_api_key),
            "messages": messages,
            "tools": tools,
            "tool_choice": None,
            "max_tokens": 1000,
            "extra_body": {"thinking": {"type": "enabled"}},
            "stream": True,
        }

        for event in self.llm_client.stream_chat_events(
            messages=messages,
            tools=tools,
            max_tokens=1000,
            extra_body={"thinking": {"type": "enabled"}},
        ):
            events.append(event)
            if on_event:
                on_event(event)
            if event["type"] == "message":
                final_message = event["message"]

        if final_message is None:
            raise AgentRuntimeError("LLM stream did not produce a final assistant message.")
        self._write_req_res_log(
            session_id=session_id,
            turn_id=turn_id,
            step=step,
            request=request,
            response=final_message,
            events=events,
        )
        return final_message, events

    def _execute_tool_call(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.registry.execute_tool_call(tool_call)
        except Exception as exc:  # noqa: BLE001 - tool errors should become observations
            function = tool_call.get("function") if isinstance(tool_call, dict) else {}
            tool_name = function.get("name", "unknown") if isinstance(function, dict) else "unknown"
            return {
                "tool": tool_name,
                "arguments": function.get("arguments", {}) if isinstance(function, dict) else {},
                "result": {"error": str(exc)},
                "error": str(exc),
                "tool_call_id": tool_call.get("id", "") if isinstance(tool_call, dict) else "",
                "type": tool_call.get("type", "function") if isinstance(tool_call, dict) else "function",
            }

    def _system_prompt_with_runtime_context(self) -> str:
        return f"{self.system_prompt}\n\n{build_runtime_context()}"

    def _write_req_res_log(
        self,
        session_id: str,
        turn_id: str,
        step: int,
        request: dict[str, Any],
        response: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> None:
        path = self.memory_store.root_dir / f"{session_id}.req_res.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "time": datetime.now(ZoneInfo(self.DEFAULT_TIMEZONE)).isoformat(),
            "session_id": session_id,
            "turn_id": turn_id,
            "step": step,
            "request": request,
            "response": response,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write("\n" + "=" * 100 + "\n")
            f.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            f.write("\n")


def resolve_session_id(session_id: str | None) -> str:
    if session_id and session_id.strip():
        return session_id.strip()
    now = datetime.now(ZoneInfo(AgentRuntime.DEFAULT_TIMEZONE))
    return f"{now:%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"


def build_runtime_context() -> str:
    now = datetime.now(ZoneInfo(AgentRuntime.DEFAULT_TIMEZONE))
    return "\n".join(
        [
            "<runtime_context>",
            f"Current date: {now:%Y-%m-%d}",
            f"Current time: {now:%H:%M:%S}",
            f"Timezone: {AgentRuntime.DEFAULT_TIMEZONE}",
            "Locale: zh-CN",
            "</runtime_context>",
        ]
    )


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}***{value[-4:]}"
