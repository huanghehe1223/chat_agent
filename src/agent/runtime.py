"""Agent runtime loop."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo
from uuid import uuid4

from src.agent.config import AgentConfig, load_config
from src.agent.llm import DeepSeekClient
from src.agent.memory import (
    DEFAULT_SESSION_NAME,
    SessionMemoryStore,
    build_llm_context,
    first_user_prompt,
    new_session_id,
    should_generate_session_title,
)
from src.agent.schemas import AssistantMessage
from src.agent.trace import TraceLogger
from src.tools.registry import ToolRegistry, build_default_registry


StreamEventHandler = Callable[[dict[str, Any]], None]


class StreamingLLMClient(Protocol):
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return one assistant message."""

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
        "search 工具只在以下情况使用：用户明确要求搜索、查询、联网确认；"
        "问题依赖当前日期、最新进展、价格、天气、新闻、版本、政策等实时性信息；"
        "或者你自身知识储备不足以可靠回答。"
        "对于稳定常识、简单计算、纯聊天或可由已有上下文可靠回答的问题，不要调用 search。"
        "当用户要求创建任务列表或给出多步骤任务时，必须先调用 manage_todo_list 提交完整任务列表。"
        "任何任务状态变化都必须立刻再次调用 manage_todo_list 提交完整列表："
        "开始执行某个任务前把它标记为 in-progress；"
        "完成某个任务后、给出最终答复前把它标记为 completed；"
        "未处理任务保持 not-started。"
        "不要只在文字中说明任务完成，任务状态必须通过工具写回。"
    )
    DEFAULT_TIMEZONE = "Asia/Shanghai"
    DEFAULT_MAX_TOKENS = 65536
    TITLE_MAX_TOKENS = 500
    TITLE_SYSTEM_PROMPT = (
        "你负责为聊天会话生成标题。只返回标题本身，不要解释，不要加引号。"
        "标题必须和用户第一条消息使用相同语言。"
        "中文标题不超过10个汉字；英文标题不超过10个单词；其他语言同样保持简短。"
    )
    MAX_STEPS_FINAL_PROMPT = (
        "已达到本轮最大推理步数限制。请不要再调用工具，请根据当前已有的对话历史和工具结果给出最终答案。"
        "如果信息不足，请说明当前能确定的内容和缺失的信息。"
    )

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
        self._title_generation_lock = threading.Lock()
        self._title_generation_sessions: set[str] = set()
        self._title_generation_pending_retry: set[str] = set()

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
        self._start_session_title_generation(session_id)
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
                if on_event:
                    on_event({"type": "tool_result", "execution": execution, "trace": trace_record})
                self.memory_store.append_tool_message(
                    session_id=session_id,
                    tool_call_id=execution.get("tool_call_id", ""),
                    name=execution.get("tool", "unknown"),
                    result=execution.get("result", {"error": execution.get("error", "unknown error")}),
                )

            if step == self.config.max_agent_steps and tool_executions:
                return self._finalize_after_max_steps(
                    session_id=session_id,
                    turn_id=turn_id,
                    step=step + 1,
                    tool_executions=tool_executions,
                    last_reasoning=last_reasoning,
                    on_event=on_event,
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
        tools: list[dict[str, Any]] | None,
        on_event: StreamEventHandler | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        events: list[dict[str, Any]] = []
        final_message: dict[str, Any] | None = None
        request = {
            "model": self.config.deepseek_model,
            "base_url": self.config.deepseek_base_url,
            "api_key": _mask_secret(self.config.deepseek_api_key),
            "messages": messages,
            "tool_choice": None,
            "max_tokens": self.DEFAULT_MAX_TOKENS,
            "extra_body": {"thinking": {"type": "enabled"}},
            "stream": True,
        }
        if tools is not None:
            request["tools"] = tools

        for event in self.llm_client.stream_chat_events(
            messages=messages,
            tools=tools,
            max_tokens=self.DEFAULT_MAX_TOKENS,
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

    def _finalize_after_max_steps(
        self,
        session_id: str,
        turn_id: str,
        step: int,
        tool_executions: list[dict[str, Any]],
        last_reasoning: str,
        on_event: StreamEventHandler | None,
    ) -> AgentTurnResult:
        session = self.memory_store.load(session_id)
        messages = build_llm_context(session, system_prompt=self._system_prompt_with_runtime_context())
        messages.append({"role": "user", "content": self.MAX_STEPS_FINAL_PROMPT})
        message, _events = self._stream_once(
            session_id=session_id,
            turn_id=turn_id,
            step=step,
            messages=messages,
            tools=None,
            on_event=on_event,
        )
        assistant_message = AssistantMessage.from_api_message(message)
        if not assistant_message.content:
            assistant_message = AssistantMessage(
                role="assistant",
                content="已达到本轮最大工具调用步数限制。当前已有工具结果，但模型没有生成可用的最终答案。",
                reasoning_content=assistant_message.reasoning_content or last_reasoning,
            )
        self.memory_store.append_assistant_message(session_id, assistant_message)
        return AgentTurnResult(
            session_id=session_id,
            turn_id=turn_id,
            answer=assistant_message.content,
            reasoning_content=assistant_message.reasoning_content,
            steps=self.config.max_agent_steps,
            tool_executions=tool_executions,
            messages=self.memory_store.load(session_id)["messages"],
        )

    def _system_prompt_with_runtime_context(self) -> str:
        return f"{self.system_prompt}\n\n{build_runtime_context()}"

    def _start_session_title_generation(self, session_id: str) -> None:
        session = self.memory_store.load(session_id)
        if not should_generate_session_title(session):
            return

        with self._title_generation_lock:
            if session_id in self._title_generation_sessions:
                self._title_generation_pending_retry.add(session_id)
                return
            self._title_generation_sessions.add(session_id)

        thread = threading.Thread(
            target=self._generate_session_title_worker,
            args=(session_id,),
            daemon=True,
            name=f"session-title-{session_id[:8]}",
        )
        thread.start()

    def _generate_session_title_worker(self, session_id: str) -> None:
        try:
            self._maybe_generate_session_title(session_id)
        finally:
            with self._title_generation_lock:
                self._title_generation_sessions.discard(session_id)
                should_retry = session_id in self._title_generation_pending_retry
                self._title_generation_pending_retry.discard(session_id)
            if should_retry and should_generate_session_title(self.memory_store.load(session_id)):
                self._start_session_title_generation(session_id)

    def _maybe_generate_session_title(self, session_id: str) -> None:
        session = self.memory_store.load(session_id)
        if not should_generate_session_title(session):
            return

        prompt = first_user_prompt(session)
        if not prompt:
            return

        try:
            title = self._generate_session_title(prompt)
        except Exception as exc:  # noqa: BLE001 - title failure should not break chat
            self._record_session_title_error(session_id, exc)
            return
        if not _is_valid_generated_title(title):
            self._record_session_title_error(session_id, ValueError("generated title was empty or default"))
            return

        self.memory_store.update_session_name(session_id, title)

    def _generate_session_title(self, first_prompt: str) -> str:
        message = self.llm_client.chat(
            messages=[
                {"role": "system", "content": self.TITLE_SYSTEM_PROMPT},
                {"role": "user", "content": f"用户第一条消息：\n{first_prompt}"},
            ],
            tools=None,
            temperature=0.2,
            max_tokens=self.TITLE_MAX_TOKENS,
        )
        return _clean_session_title(message.get("content") or "")

    def _record_session_title_error(self, session_id: str, exc: Exception) -> None:
        session = self.memory_store.load(session_id)
        session.setdefault("metadata", {})["title_generation_error"] = str(exc)
        self.memory_store.save(session)

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
    return new_session_id()


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


def _clean_session_title(value: str) -> str:
    title = " ".join(str(value or "").strip().split())
    title = title.strip(' "\'`“”‘’.,，。:：;；#')
    for prefix in ["标题：", "标题:", "Title:", "title:"]:
        if title.startswith(prefix):
            title = title[len(prefix):].strip(' "\'`“”‘’.,，。:：;；#')
            break
    if not title:
        return DEFAULT_SESSION_NAME

    words = title.split()
    if len(words) > 1:
        return " ".join(words[:10]).strip()
    if len(title) > 10:
        return title[:10].strip()
    return title


def _is_valid_generated_title(value: str) -> bool:
    title = str(value or "").strip()
    return bool(title) and title != DEFAULT_SESSION_NAME
