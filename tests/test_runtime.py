from pathlib import Path
import json
import re
from typing import Any

from src.agent.config import AgentConfig
from src.agent.memory import SessionMemoryStore
from src.agent.runtime import AgentRuntime
from src.agent.trace import TraceLogger
from src.tools.registry import build_default_registry


class FakeStreamingLLM:
    def __init__(self, event_batches: list[list[dict[str, Any]]]) -> None:
        self.event_batches = event_batches
        self.calls: list[dict[str, Any]] = []

    def stream_chat_events(
        self,
        messages,
        tools=None,
        tool_choice=None,
        temperature=None,
        max_tokens=None,
        extra_body=None,
    ):
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "extra_body": extra_body,
            }
        )
        events = self.event_batches.pop(0)
        yield from events


def make_runtime(tmp_path: Path, fake_llm: FakeStreamingLLM, max_steps: int = 5) -> AgentRuntime:
    config = AgentConfig(deepseek_api_key="test-key", max_agent_steps=max_steps)
    return AgentRuntime(
        config=config,
        llm_client=fake_llm,
        memory_store=SessionMemoryStore(tmp_path / "sessions"),
        registry=build_default_registry(config, todo_store_path=tmp_path / "todos.json"),
        trace_logger=TraceLogger(tmp_path / "traces"),
        system_prompt="You are a test agent.",
    )


def test_runtime_supports_multi_turn_context_without_reasoning_content(tmp_path: Path):
    fake_llm = FakeStreamingLLM(
        [
            [
                {"type": "content_delta", "delta": "你好"},
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": "你好",
                        "reasoning_content": "Greet briefly.",
                    },
                },
            ],
            [
                {"type": "content_delta", "delta": "你刚才说了你好"},
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": "你刚才说了你好",
                        "reasoning_content": "Use previous context.",
                    },
                },
            ],
        ]
    )
    runtime = make_runtime(tmp_path, fake_llm)

    first = runtime.run_turn("你好", session_id="demo")
    second = runtime.run_turn("我刚才说了什么？", session_id="demo")

    assert first.answer == "你好"
    assert second.answer == "你刚才说了你好"
    second_messages = fake_llm.calls[1]["messages"]
    assert {"role": "user", "content": "你好"} in second_messages
    assert {"role": "assistant", "content": "你好"} in second_messages
    assert "reasoning_content" not in str(second_messages)


def test_runtime_executes_tool_call_and_continues_llm_loop(tmp_path: Path):
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "calculator",
            "arguments": '{"expression": "(12 + 8) * 3"}',
        },
    }
    fake_llm = FakeStreamingLLM(
        [
            [
                {"type": "reasoning_delta", "delta": "Need calculator."},
                {"type": "tool_call", "tool_call": tool_call},
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "Need calculator.",
                        "tool_calls": [tool_call],
                    },
                    "finish_reason": "tool_calls",
                },
            ],
            [
                {"type": "content_delta", "delta": "结果是 60。"},
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": "结果是 60。",
                        "reasoning_content": "Use tool result.",
                    },
                    "finish_reason": "stop",
                },
            ],
        ]
    )
    runtime = make_runtime(tmp_path, fake_llm)
    seen_events: list[dict[str, Any]] = []

    result = runtime.run_turn(
        "帮我算一下 (12 + 8) * 3",
        session_id="demo",
        on_event=seen_events.append,
    )

    assert result.answer == "结果是 60。"
    assert result.steps == 2
    assert result.tool_executions[0]["tool"] == "calculator"
    assert result.tool_executions[0]["result"]["result"] == 60
    assert any(event["type"] == "tool_result" for event in seen_events)
    trace_records = runtime.trace_logger.read_records("demo")
    assert trace_records[0]["session_id"] == "demo"
    assert trace_records[0]["tool"] == "calculator"
    assert trace_records[0]["arguments"] == {"expression": "(12 + 8) * 3"}
    assert trace_records[0]["result"]["result"] == 60

    second_call_messages = fake_llm.calls[1]["messages"]
    assert any(message["role"] == "tool" and "60" in message["content"] for message in second_call_messages)
    assert "reasoning_content" not in str(second_call_messages)

    stored_roles = [message["role"] for message in result.messages]
    assert stored_roles == ["user", "assistant", "tool", "assistant"]


def test_runtime_persists_manage_todo_list_to_session_memory(tmp_path: Path):
    tool_call = {
        "id": "call_todo",
        "type": "function",
        "function": {
            "name": "manage_todo_list",
            "arguments": (
                '{"todoList": ['
                '{"id": 1, "title": "实现 runtime", "status": "completed"},'
                '{"id": 2, "title": "完善 CLI", "status": "in-progress"}'
                "]}"
            ),
        },
    }
    fake_llm = FakeStreamingLLM(
        [
            [
                {"type": "tool_call", "tool_call": tool_call},
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [tool_call],
                    },
                    "finish_reason": "tool_calls",
                },
            ],
            [
                {"type": "content_delta", "delta": "任务列表已更新。"},
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": "任务列表已更新。",
                    },
                },
            ],
        ]
    )
    runtime = make_runtime(tmp_path, fake_llm)
    seen_events: list[dict[str, Any]] = []

    result = runtime.run_turn("规划一下任务", session_id="demo", on_event=seen_events.append)

    todo_list = runtime.memory_store.get_todo_list("demo")
    assert result.answer == "任务列表已更新。"
    assert [
        {key: item[key] for key in ["id", "title", "status"]}
        for item in todo_list
    ] == [
        {"id": 1, "title": "实现 runtime", "status": "completed"},
        {"id": 2, "title": "完善 CLI", "status": "in-progress"},
    ]
    assert any(event["type"] == "task_list" for event in seen_events)
    event_types = [event["type"] for event in seen_events]
    assert event_types.index("task_list") < event_types.index("tool_result")
    assert fake_llm.calls[1]["messages"][0]["role"] == "system"
    assert "完善 CLI" in fake_llm.calls[1]["messages"][0]["content"]


def test_runtime_uses_thinking_mode_and_default_tool_choice(tmp_path: Path):
    fake_llm = FakeStreamingLLM(
        [
            [
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": "OK",
                        "reasoning_content": "Short thought.",
                    },
                }
            ]
        ]
    )
    runtime = make_runtime(tmp_path, fake_llm)

    runtime.run_turn("ping", session_id="demo")

    call = fake_llm.calls[0]
    assert call["extra_body"] == {"thinking": {"type": "enabled"}}
    assert call["max_tokens"] == AgentRuntime.DEFAULT_MAX_TOKENS == 65536
    assert call["tool_choice"] is None
    assert call["tools"]


def test_default_system_prompt_requires_todo_status_writeback():
    prompt = AgentRuntime.DEFAULT_SYSTEM_PROMPT

    assert "必须先调用 manage_todo_list 提交完整任务列表" in prompt
    assert "完成某个任务后、给出最终答复前把它标记为 completed" in prompt
    assert "任务状态必须通过工具写回" in prompt


def test_default_system_prompt_constrains_search_usage():
    prompt = AgentRuntime.DEFAULT_SYSTEM_PROMPT

    assert "用户明确要求搜索、查询、联网确认" in prompt
    assert "当前日期、最新进展、价格、天气、新闻、版本、政策" in prompt
    assert "自身知识储备不足以可靠回答" in prompt
    assert "稳定常识、简单计算、纯聊天" in prompt
    assert "不要调用 search" in prompt


def test_runtime_injects_shanghai_runtime_context_and_writes_req_res_log(tmp_path: Path):
    fake_llm = FakeStreamingLLM(
        [
            [
                {
                    "type": "content_delta",
                    "delta": "OK",
                    "chunk": {"choices": [{"delta": {"content": "OK"}}]},
                },
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": "OK",
                        "reasoning_content": "Short thought.",
                        "_stream_chunks": [{"choices": [{"delta": {"content": "OK"}}]}],
                    },
                    "finish_reason": "stop",
                },
            ]
        ]
    )
    runtime = make_runtime(tmp_path, fake_llm)

    runtime.run_turn("ping", session_id="demo")

    request_messages = fake_llm.calls[0]["messages"]
    assert request_messages[0]["role"] == "system"
    assert "<runtime_context>" in request_messages[0]["content"]
    assert "Timezone: Asia/Shanghai" in request_messages[0]["content"]
    assert "Locale: zh-CN" in request_messages[0]["content"]

    log_file = tmp_path / "sessions" / "demo.req_res.log"
    log_text = log_file.read_text(encoding="utf-8")
    payload = json.loads(log_text.split("=" * 100)[-1])

    assert payload["session_id"] == "demo"
    assert payload["request"]["api_key"] == "***"
    assert payload["request"]["stream"] is True
    assert payload["request"]["max_tokens"] == 65536
    assert payload["request"]["messages"][0] == request_messages[0]
    assert payload["response"]["content"] == "OK"
    assert "response_chunks" not in payload
    assert payload["response"]["_stream_chunks"] == [{"choices": [{"delta": {"content": "OK"}}]}]


def test_runtime_blank_session_id_generates_timestamp_uuid_session(tmp_path: Path):
    fake_llm = FakeStreamingLLM(
        [
            [
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": "OK",
                    },
                }
            ]
        ]
    )
    runtime = make_runtime(tmp_path, fake_llm)

    result = runtime.run_turn("ping", session_id="")

    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{8}", result.session_id)
    assert (tmp_path / "sessions" / f"{result.session_id}.json").exists()
    assert (tmp_path / "sessions" / f"{result.session_id}.req_res.log").exists()


def test_runtime_finalizes_without_tools_after_max_steps_with_tool_result(tmp_path: Path):
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "calculator",
            "arguments": '{"expression": "(12 + 8) * 3"}',
        },
    }
    fake_llm = FakeStreamingLLM(
        [
            [
                {"type": "tool_call", "tool_call": tool_call},
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "Need calculator.",
                        "tool_calls": [tool_call],
                    },
                    "finish_reason": "tool_calls",
                },
            ],
            [
                {"type": "content_delta", "delta": "根据工具结果，答案是 60。"},
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": "根据工具结果，答案是 60。",
                        "reasoning_content": "Summarize existing tool result.",
                    },
                    "finish_reason": "stop",
                },
            ],
        ]
    )
    runtime = make_runtime(tmp_path, fake_llm, max_steps=1)

    result = runtime.run_turn("帮我算一下 (12 + 8) * 3", session_id="demo")

    assert result.answer == "根据工具结果，答案是 60。"
    assert result.steps == 1
    assert len(fake_llm.calls) == 2
    assert fake_llm.calls[1]["tools"] is None
    assert fake_llm.calls[1]["messages"][-1] == {
        "role": "user",
        "content": runtime.MAX_STEPS_FINAL_PROMPT,
    }
    assert any(
        message["role"] == "tool" and "60" in message["content"]
        for message in fake_llm.calls[1]["messages"]
    )
    assert result.messages[-1]["content"] == "根据工具结果，答案是 60。"
