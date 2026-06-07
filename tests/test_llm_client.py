from datetime import datetime, timezone
import json
from pathlib import Path

from src.agent.config import load_config
from src.agent.llm import DeepSeekClient
from src.agent.schemas import AssistantMessage


LOG_FILE = Path("logs/deepseek_real_api.log")


def write_llm_response_log(
    test_name: str,
    message: AssistantMessage,
    request: dict | None = None,
) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "time": datetime.now(timezone.utc).isoformat(),
        "test_name": test_name,
        "request": request,
        "response": {
            "role": message.role,
            "content": message.content,
            "reasoning_content": message.reasoning_content,
            "tool_calls": message.tool_calls,
        },
    }
    if message.raw.get("_stream_chunks"):
        payload["raw_stream_chunks"] = message.raw["_stream_chunks"]

    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write("\n" + "=" * 100 + "\n")
        f.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        f.write("\n")


def calculator_tool_schema() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "Calculate a simple arithmetic expression.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "The arithmetic expression to calculate.",
                        }
                    },
                    "required": ["expression"],
                },
            },
        }
    ]


def test_stream_response_parser_merges_reasoning_content_and_tool_calls():
    chunks = [
        {"choices": [{"delta": {"role": "assistant"}}]},
        {"choices": [{"delta": {"reasoning_content": "Think "}}]},
        {"choices": [{"delta": {"reasoning_content": "briefly. "}}]},
        {"choices": [{"delta": {"content": "OK"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "calculator", "arguments": "{\"expression\""},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": ": \"(12 + 8) * 3\"}"},
                            }
                        ]
                    }
                }
            ]
        },
    ]

    message = DeepSeekClient._extract_stream_message(chunks)

    assert message["role"] == "assistant"
    assert message["reasoning_content"] == "Think briefly. "
    assert message["content"] == "OK"
    assert message["tool_calls"] == [
        {
            "index": 0,
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "calculator",
                "arguments": "{\"expression\": \"(12 + 8) * 3\"}",
            },
        }
    ]


def test_stream_events_yield_deltas_before_full_stream_is_consumed():
    chunks = [
        {"choices": [{"delta": {"role": "assistant"}}]},
        {"choices": [{"delta": {"reasoning_content": "Think "}}]},
        {"choices": [{"delta": {"content": "O"}}]},
        {"choices": [{"delta": {"content": "K"}, "finish_reason": "stop"}]},
    ]
    pulled_chunks = []

    def chunk_iter():
        for chunk in chunks:
            pulled_chunks.append(chunk)
            yield chunk

    events = DeepSeekClient._iter_stream_events(chunk_iter())
    first_event = next(events)

    assert first_event == {
        "type": "reasoning_delta",
        "delta": "Think ",
        "chunk": chunks[1],
    }
    assert len(pulled_chunks) == 2
    assert len(pulled_chunks) < len(chunks)


def test_stream_events_emit_complete_tool_call_before_final_message():
    chunks = [
        {"choices": [{"delta": {"role": "assistant"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "calculator", "arguments": "{\"expression\""},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": ": \"(12 + 8) * 3\"}"},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ]

    events = list(DeepSeekClient._iter_stream_events(chunks))
    event_types = [event["type"] for event in events]
    tool_call_event = events[event_types.index("tool_call")]
    final_message_event = events[event_types.index("message")]

    assert event_types == ["tool_call_delta", "tool_call_delta", "tool_call", "message"]
    assert tool_call_event["tool_call"] == {
        "index": 0,
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "calculator",
            "arguments": "{\"expression\": \"(12 + 8) * 3\"}",
        },
    }
    assert final_message_event["message"]["tool_calls"] == [tool_call_event["tool_call"]]


def test_deepseek_real_chat_completion_with_thinking():
    config = load_config()
    client = DeepSeekClient(config)
    messages = [
        {"role": "system", "content": "You are a concise test assistant."},
        {"role": "user", "content": "Think briefly, then reply with exactly: OK"},
    ]
    request = {
        "model": config.deepseek_model,
        "messages": messages,
        "stream": False,
        "max_tokens": 1000,
        "extra_body": {"thinking": {"type": "enabled"}},
    }

    message = client.chat_parsed(
        messages=messages,
        max_tokens=1000,
        extra_body={"thinking": {"type": "enabled"}},
    )

    write_llm_response_log(
        "test_deepseek_real_chat_completion_with_thinking",
        message,
        request,
    )

    assert message.role == "assistant"
    assert message.reasoning_content
    assert "OK" in message.content


def test_deepseek_real_stream_chat_completion_with_thinking():
    config = load_config()
    client = DeepSeekClient(config)
    messages = [
        {"role": "system", "content": "You are a concise test assistant."},
        {"role": "user", "content": "Think briefly, then reply with exactly: OK"},
    ]
    request = {
        "model": config.deepseek_model,
        "messages": messages,
        "stream": True,
        "max_tokens": 1000,
        "extra_body": {"thinking": {"type": "enabled"}},
    }

    message = client.chat_stream_parsed(
        messages=messages,
        max_tokens=1000,
        extra_body={"thinking": {"type": "enabled"}},
    )

    write_llm_response_log(
        "test_deepseek_real_stream_chat_completion_with_thinking",
        message,
        request,
    )

    assert message.role == "assistant"
    assert message.reasoning_content
    assert "OK" in message.content


def test_deepseek_real_tool_call_response_with_thinking():
    config = load_config()
    client = DeepSeekClient(config)
    tools = calculator_tool_schema()
    messages = [
        {
            "role": "user",
            "content": (
                "You must use the calculator tool to calculate (12 + 8) * 3. "
                "Do not answer directly before calling the tool."
            ),
        }
    ]
    request = {
        "model": config.deepseek_model,
        "messages": messages,
        "tools": tools,
        "stream": False,
        "max_tokens": 1000,
        "extra_body": {"thinking": {"type": "enabled"}},
    }

    message = client.chat_parsed(
        messages=messages,
        tools=tools,
        max_tokens=1000,
        extra_body={"thinking": {"type": "enabled"}},
    )

    write_llm_response_log(
        "test_deepseek_real_tool_call_response_with_thinking",
        message,
        request,
    )

    tool_calls = message.tool_calls
    assert message.role == "assistant"
    assert message.reasoning_content
    assert len(tool_calls) >= 1
    assert tool_calls[0]["type"] == "function"
    assert tool_calls[0]["function"]["name"] == "calculator"
    assert "expression" in tool_calls[0]["function"]["arguments"]


def test_deepseek_real_stream_tool_call_response_with_thinking():
    config = load_config()
    client = DeepSeekClient(config)
    tools = calculator_tool_schema()
    messages = [
        {
            "role": "user",
            "content": (
                "You must use the calculator tool to calculate (12 + 8) * 3. "
                "Do not answer directly before calling the tool."
            ),
        }
    ]
    request = {
        "model": config.deepseek_model,
        "messages": messages,
        "tools": tools,
        "stream": True,
        "max_tokens": 1000,
        "extra_body": {"thinking": {"type": "enabled"}},
    }

    message = client.chat_stream_parsed(
        messages=messages,
        tools=tools,
        max_tokens=1000,
        extra_body={"thinking": {"type": "enabled"}},
    )

    write_llm_response_log(
        "test_deepseek_real_stream_tool_call_response_with_thinking",
        message,
        request,
    )

    tool_calls = message.tool_calls
    assert message.role == "assistant"
    assert message.reasoning_content
    assert len(tool_calls) >= 1
    assert tool_calls[0]["type"] == "function"
    assert tool_calls[0]["function"]["name"] == "calculator"
    assert "expression" in tool_calls[0]["function"]["arguments"]
