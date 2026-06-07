import json
from pathlib import Path
from types import SimpleNamespace

from src.agent.memory import SessionMemoryStore
from src.web import (
    choose_initial_session,
    delete_button_key,
    delete_confirm_key,
    delete_session_artifacts,
    ensure_session_exists,
    format_task_list,
    format_tool_call,
    list_session_ids,
    parse_log_blocks,
    read_last_log_block,
)


def test_list_session_ids_returns_sessions_in_created_time_order(tmp_path: Path):
    (tmp_path / "z-later.json").write_text(
        json.dumps({"metadata": {"created_at": "2026-06-07T12:00:00+00:00"}}),
        encoding="utf-8",
    )
    (tmp_path / "a-earlier.json").write_text(
        json.dumps({"metadata": {"created_at": "2026-06-07T10:00:00+00:00"}}),
        encoding="utf-8",
    )
    (tmp_path / "测试会话.json").write_text(
        json.dumps({"metadata": {"created_at": "2026-06-07T11:00:00+00:00"}}),
        encoding="utf-8",
    )
    (tmp_path / "demo.req_res.log").write_text("{}", encoding="utf-8")
    (tmp_path / ".gitkeep").write_text("", encoding="utf-8")

    assert list_session_ids(tmp_path) == ["a-earlier", "测试会话", "z-later"]


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
