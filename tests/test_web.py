import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from src.agent.memory import SessionMemoryStore
from src.web import (
    build_session_labels,
    choose_initial_session,
    create_session,
    delete_button_key,
    delete_confirm_key,
    delete_session_artifacts,
    ensure_session_exists,
    format_session_label,
    format_task_list,
    format_tool_call,
    find_default_untitled_session,
    list_session_ids,
    list_session_summaries,
    parse_log_blocks,
    read_last_log_block,
)


def test_list_session_ids_returns_sessions_in_created_time_desc_order(tmp_path: Path):
    (tmp_path / "z-later.json").write_text(
        json.dumps({"session_name": "Later", "metadata": {"created_at": "2026-06-07T12:00:00+00:00"}}),
        encoding="utf-8",
    )
    (tmp_path / "a-earlier.json").write_text(
        json.dumps({"session_name": "Earlier", "metadata": {"created_at": "2026-06-07T10:00:00+00:00"}}),
        encoding="utf-8",
    )
    (tmp_path / "测试会话.json").write_text(
        json.dumps({"metadata": {"created_at": "2026-06-07T11:00:00+00:00"}}),
        encoding="utf-8",
    )
    (tmp_path / "demo.req_res.log").write_text("{}", encoding="utf-8")
    (tmp_path / ".gitkeep").write_text("", encoding="utf-8")

    assert list_session_ids(tmp_path) == ["z-later", "测试会话", "a-earlier"]
    assert list_session_summaries(tmp_path) == [
        {"session_id": "z-later", "session_name": "Later"},
        {"session_id": "测试会话", "session_name": "测试会话"},
        {"session_id": "a-earlier", "session_name": "Earlier"},
    ]


def test_format_session_label_uses_display_name():
    assert format_session_label({"session_id": "demo", "session_name": "demo"}) == "demo"
    assert format_session_label({"session_id": "12345678-aaaa", "session_name": "New Chat"}) == "New Chat"


def test_build_session_labels_disambiguates_duplicate_user_names():
    labels = build_session_labels(
        [
            {"session_id": "aaaaaaaa-1111", "session_name": "New Chat"},
            {"session_id": "bbbbbbbb-2222", "session_name": "New Chat"},
            {"session_id": "cccccccc-3333", "session_name": "RAG调研"},
        ]
    )

    assert labels == {
        "aaaaaaaa-1111": "New Chat · aaaaaaaa",
        "bbbbbbbb-2222": "New Chat · bbbbbbbb",
        "cccccccc-3333": "RAG调研",
    }


def test_choose_initial_session_prefers_query_then_first_session():
    sessions = ["alpha", "beta", "测试会话"]

    assert choose_initial_session("beta", sessions) == "beta"
    assert choose_initial_session("missing", sessions) == "alpha"
    assert choose_initial_session(None, sessions) == "alpha"


def test_delete_widget_keys_are_scoped_by_session():
    assert delete_confirm_key("alpha") != delete_confirm_key("beta")
    assert delete_button_key("alpha") != delete_button_key("beta")
    assert delete_confirm_key("测试会话") == "confirm_delete::测试会话"


def test_format_tool_call_pretty_prints_arguments():
    text = format_tool_call(
        {
            "id": "call_1",
            "function": {
                "name": "calculator",
                "arguments": '{"expression": "(12 + 8) * 3"}',
            },
        }
    )

    assert "calculator (call_1)" in text
    assert '"expression": "(12 + 8) * 3"' in text


def test_format_task_list():
    lines = format_task_list(
        [
            {"id": 1, "title": "实现 runtime", "status": "completed"},
            {"id": 2, "title": "完善 Web", "status": "in-progress"},
        ]
    )

    assert lines == [
        "1. [completed] 实现 runtime",
        "2. [in-progress] 完善 Web",
    ]


def test_parse_log_blocks_reads_req_res_log(tmp_path: Path):
    path = tmp_path / "demo.req_res.log"
    first = {"step": 1, "response": {"content": "OK"}}
    second = {"step": 2, "response": {"content": "done"}}
    path.write_text(
        "\n====================================================================================================\n"
        + json.dumps(first, ensure_ascii=False)
        + "\n====================================================================================================\n"
        + json.dumps(second, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    assert parse_log_blocks(path) == [first, second]
    assert read_last_log_block(path) == json.dumps(second, ensure_ascii=False)


def test_ensure_session_exists_creates_empty_session_file(tmp_path: Path):
    runtime = SimpleNamespace(memory_store=SessionMemoryStore(tmp_path))

    ensure_session_exists(runtime, "新会话")

    assert (tmp_path / "新会话.json").exists()
    assert list_session_ids(tmp_path) == ["新会话"]


def test_create_session_uses_input_as_display_name_not_filename(tmp_path: Path):
    runtime = SimpleNamespace(memory_store=SessionMemoryStore(tmp_path))

    session_id = create_session(runtime, "test-agent-1")

    assert str(UUID(session_id)) == session_id
    assert (tmp_path / f"{session_id}.json").exists()
    assert not (tmp_path / "test-agent-1.json").exists()
    assert runtime.memory_store.load(session_id)["session_name"] == "test-agent-1"


def test_create_session_defaults_display_name(tmp_path: Path):
    runtime = SimpleNamespace(memory_store=SessionMemoryStore(tmp_path))

    session_id = create_session(runtime, "")

    assert runtime.memory_store.load(session_id)["session_name"] == "New Chat"


def test_create_session_reuses_existing_default_untitled_session(tmp_path: Path):
    runtime = SimpleNamespace(memory_store=SessionMemoryStore(tmp_path))

    first_session_id = create_session(runtime, "")
    runtime.memory_store.append_user_message(first_session_id, "hello")
    second_session_id = create_session(runtime, "")

    assert second_session_id == first_session_id
    assert list_session_ids(tmp_path) == [first_session_id]


def test_create_session_reuses_invalid_generated_new_chat(tmp_path: Path):
    runtime = SimpleNamespace(memory_store=SessionMemoryStore(tmp_path))
    session_id = "cbd0edea-6dd8-43e9-9f6b-237e0bd3bb2b"
    (tmp_path / f"{session_id}.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "session_name": "New Chat",
                "messages": [{"role": "user", "content": "早上好啊"}],
                "memory": {"tasks": {}, "facts": {}, "preferences": {}},
                "metadata": {"session_name_source": "generated"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    new_session_id = create_session(runtime, "")

    assert new_session_id == session_id
    assert list_session_ids(tmp_path) == [session_id]


def test_find_default_untitled_session_supports_old_memory_store_object(tmp_path: Path):
    session_id = "cbd0edea-6dd8-43e9-9f6b-237e0bd3bb2b"
    (tmp_path / f"{session_id}.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "session_name": "New Chat",
                "messages": [{"role": "user", "content": "早上好啊"}],
                "memory": {"tasks": {}, "facts": {}, "preferences": {}},
                "metadata": {
                    "created_at": "2026-06-07T13:07:37+00:00",
                    "session_name_source": "generated",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    old_store = SimpleNamespace(root_dir=tmp_path)

    assert find_default_untitled_session(old_store) == session_id


def test_create_session_allows_user_named_new_chat_sessions(tmp_path: Path):
    runtime = SimpleNamespace(memory_store=SessionMemoryStore(tmp_path))

    first_session_id = create_session(runtime, "New Chat")
    second_session_id = create_session(runtime, "New Chat")

    assert first_session_id != second_session_id
    assert len(list_session_ids(tmp_path)) == 2
    assert runtime.memory_store.load(first_session_id)["metadata"]["session_name_source"] == "user"


def test_delete_session_artifacts_removes_session_logs_and_trace(tmp_path: Path):
    session_dir = tmp_path / "sessions"
    trace_dir = tmp_path / "traces"
    session_dir.mkdir()
    trace_dir.mkdir()
    (session_dir / "demo.json").write_text("{}", encoding="utf-8")
    (session_dir / "demo.req_res.log").write_text("log", encoding="utf-8")
    (trace_dir / "demo.trace.log").write_text("trace", encoding="utf-8")
    (session_dir / "other.json").write_text("{}", encoding="utf-8")

    deleted = delete_session_artifacts("demo", session_dir=session_dir, trace_dir=trace_dir)

    assert sorted(path.name for path in deleted) == ["demo.json", "demo.req_res.log", "demo.trace.log"]
    assert not (session_dir / "demo.json").exists()
    assert not (session_dir / "demo.req_res.log").exists()
    assert not (trace_dir / "demo.trace.log").exists()
    assert (session_dir / "other.json").exists()
