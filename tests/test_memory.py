import json
from pathlib import Path
from uuid import UUID

import pytest

from src.agent.memory import (
    DEFAULT_SESSION_NAME,
    SESSION_NAME_SOURCE_DEFAULT,
    SESSION_NAME_SOURCE_GENERATED,
    SESSION_NAME_SOURCE_USER,
    MemoryError,
    SessionMemoryStore,
    build_llm_context,
    first_user_prompt,
    should_generate_session_title,
)
from src.agent.schemas import AssistantMessage


def test_session_store_creates_and_persists_session(tmp_path: Path):
    store = SessionMemoryStore(tmp_path)

    session = store.append_user_message("demo", "你好")
    loaded = store.load("demo")

    assert session["session_id"] == "demo"
    assert loaded["messages"][0]["role"] == "user"
    assert loaded["messages"][0]["content"] == "你好"
    assert (tmp_path / "demo.json").exists()


def test_session_store_supports_chinese_session_id(tmp_path: Path):
    store = SessionMemoryStore(tmp_path)

    session = store.append_user_message("测试会话", "你好")

    assert session["session_id"] == "测试会话"
    assert (tmp_path / "测试会话.json").exists()


def test_session_store_creates_uuid_session_with_display_name(tmp_path: Path):
    store = SessionMemoryStore(tmp_path)

    session = store.create("test-agent-1")

    assert session["session_name"] == "test-agent-1"
    assert str(UUID(session["session_id"])) == session["session_id"]
    assert session["session_id"] != "test-agent-1"
    assert session["metadata"]["session_name_source"] == SESSION_NAME_SOURCE_USER
    assert (tmp_path / f"{session['session_id']}.json").exists()
    assert not (tmp_path / "test-agent-1.json").exists()


def test_session_store_defaults_new_session_name(tmp_path: Path):
    store = SessionMemoryStore(tmp_path)

    session = store.create("")

    assert session["session_name"] == DEFAULT_SESSION_NAME
    assert session["metadata"]["session_name_source"] == SESSION_NAME_SOURCE_DEFAULT


def test_user_can_explicitly_name_session_new_chat(tmp_path: Path):
    store = SessionMemoryStore(tmp_path)

    session = store.create(DEFAULT_SESSION_NAME)

    assert session["session_name"] == DEFAULT_SESSION_NAME
    assert session["metadata"]["session_name_source"] == SESSION_NAME_SOURCE_USER
    assert not should_generate_session_title(session)


def test_session_title_generation_state_uses_first_user_prompt(tmp_path: Path):
    store = SessionMemoryStore(tmp_path)
    session = store.create("")

    session = store.append_user_message(session["session_id"], "帮我规划一次RAG调研")
    session = store.append_assistant_message(
        session["session_id"],
        {"role": "assistant", "content": "好的"},
    )

    assert should_generate_session_title(session)
    assert first_user_prompt(session) == "帮我规划一次RAG调研"


def test_session_name_update_marks_generated_source(tmp_path: Path):
    store = SessionMemoryStore(tmp_path)
    session = store.create("")

    updated = store.update_session_name(session["session_id"], "RAG调研")

    assert updated["session_name"] == "RAG调研"
    assert updated["metadata"]["session_name_source"] == SESSION_NAME_SOURCE_GENERATED
    assert "title_generated_at" in updated["metadata"]


def test_find_default_untitled_session_reuses_unrenamed_default_sessions(tmp_path: Path):
    store = SessionMemoryStore(tmp_path)
    untitled = store.create("")
    named = store.create("New Chat")
    store.append_user_message(untitled["session_id"], "hello")

    assert store.find_default_untitled_session() == untitled["session_id"]
    assert named["session_id"] != untitled["session_id"]


def test_generated_new_chat_is_treated_as_default_untitled(tmp_path: Path):
    session_id = "cbd0edea-6dd8-43e9-9f6b-237e0bd3bb2b"
    (tmp_path / f"{session_id}.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "session_name": "New Chat",
                "messages": [{"role": "user", "content": "早上好啊"}],
                "memory": {"tasks": {}, "facts": {}, "preferences": {}},
                "metadata": {
                    "session_name_source": "generated",
                    "title_generated_at": "2026-06-07T13:07:45+00:00",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = SessionMemoryStore(tmp_path)

    session = store.load(session_id)

    assert session["metadata"]["session_name_source"] == SESSION_NAME_SOURCE_DEFAULT
    assert "title_generated_at" not in session["metadata"]
    assert should_generate_session_title(session)


def test_assistant_message_keeps_reasoning_locally_but_filters_llm_context(tmp_path: Path):
    store = SessionMemoryStore(tmp_path)
    store.append_user_message("demo", "Think briefly, then reply OK")
    session = store.append_assistant_message(
        "demo",
        AssistantMessage(
            role="assistant",
            content="OK",
            reasoning_content="The user asked for an exact reply.",
        ),
    )

    saved_content = (tmp_path / "demo.json").read_text(encoding="utf-8")
    context = build_llm_context(session)

    assert "reasoning_content" in saved_content
    assert session["messages"][1]["reasoning_content"] == "The user asked for an exact reply."
    assert context == [
        {"role": "user", "content": "Think briefly, then reply OK"},
        {"role": "assistant", "content": "OK"},
    ]
    assert "reasoning_content" not in json.dumps(context, ensure_ascii=False)


def test_llm_context_preserves_assistant_tool_calls_and_tool_results(tmp_path: Path):
    store = SessionMemoryStore(tmp_path)
    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "calculator",
                "arguments": '{"expression": "(12 + 8) * 3"}',
            },
        }
    ]

    store.append_user_message("demo", "帮我算一下 (12 + 8) * 3")
    store.append_assistant_message(
        "demo",
        AssistantMessage(
            role="assistant",
            content="",
            reasoning_content="I should call calculator.",
            tool_calls=tool_calls,
        ),
    )
    session = store.append_tool_message(
        "demo",
        tool_call_id="call_1",
        name="calculator",
        result={"result": 60},
    )

    context = build_llm_context(session)

    assert context[1] == {
        "role": "assistant",
        "content": "",
        "tool_calls": tool_calls,
    }
    assert "reasoning_content" not in context[1]
    assert context[2] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "name": "calculator",
        "content": '{"result": 60}',
    }


def test_memory_tasks_are_saved_and_injected_as_system_summary(tmp_path: Path):
    store = SessionMemoryStore(tmp_path)
    session = store.set_task(
        "demo",
        {
            "id": "task-1",
            "title": "调研最小 Agent runtime",
            "status": "in-progress",
        },
    )

    context = build_llm_context(session, system_prompt="You are a helpful agent.")

    assert store.load("demo")["memory"]["tasks"]["task-1"]["title"] == "调研最小 Agent runtime"
    assert context[0]["role"] == "system"
    assert "You are a helpful agent." in context[0]["content"]
    assert "当前 session 任务状态" in context[0]["content"]
    assert "调研最小 Agent runtime" in context[0]["content"]
    assert "开始或完成任何任务时，必须立即调用 manage_todo_list" in context[0]["content"]
    assert "提交完整 todoList" in context[0]["content"]


def test_load_missing_session_returns_empty_session(tmp_path: Path):
    store = SessionMemoryStore(tmp_path)

    session = store.load("missing")

    assert session["session_id"] == "missing"
    assert session["messages"] == []
    assert session["memory"]["tasks"] == {}


def test_load_damaged_session_json_raises_memory_error(tmp_path: Path):
    (tmp_path / "broken.json").write_text("{not-json", encoding="utf-8")
    store = SessionMemoryStore(tmp_path)

    with pytest.raises(MemoryError, match="not valid JSON"):
        store.load("broken")


def test_session_id_rejects_path_traversal(tmp_path: Path):
    store = SessionMemoryStore(tmp_path)

    with pytest.raises(MemoryError, match="session_id"):
        store.load("../outside")


def test_session_id_rejects_path_separator(tmp_path: Path):
    store = SessionMemoryStore(tmp_path)

    with pytest.raises(MemoryError, match="session_id"):
        store.load("bad/name")
