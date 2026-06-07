import json
from pathlib import Path
from types import SimpleNamespace

from src.agent.memory import SessionMemoryStore
from src.web import ensure_session_exists, format_task_list, format_tool_call, list_session_ids, parse_log_blocks, read_last_log_block


def test_list_session_ids_only_returns_session_json_files(tmp_path: Path):
    (tmp_path / "demo.json").write_text("{}", encoding="utf-8")
    (tmp_path / "测试会话.json").write_text("{}", encoding="utf-8")
    (tmp_path / "demo.req_res.log").write_text("{}", encoding="utf-8")
    (tmp_path / ".gitkeep").write_text("", encoding="utf-8")

    assert list_session_ids(tmp_path) == ["demo", "测试会话"]


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
