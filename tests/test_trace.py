from pathlib import Path

import pytest

from src.agent.trace import TraceError, TraceLogger


def test_trace_logger_records_tool_call_summary(tmp_path: Path):
    logger = TraceLogger(tmp_path)
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "calculator",
            "arguments": '{"expression": "(12 + 8) * 3"}',
        },
    }
    execution = {
        "tool": "calculator",
        "arguments": {"expression": "(12 + 8) * 3"},
        "result": {"result": 60},
        "tool_call_id": "call_1",
        "type": "function",
    }

    record = logger.record_tool_call(
        session_id="demo",
        turn_id="turn-1",
        step=1,
        tool_call=tool_call,
        execution=execution,
    )
    records = logger.read_records("demo")

    assert record["session_id"] == "demo"
    assert records == [record]
    assert records[0]["tool"] == "calculator"
    assert records[0]["arguments"] == {"expression": "(12 + 8) * 3"}
    assert records[0]["result"] == {"result": 60}
    assert records[0]["error"] is None
    assert records[0]["raw_tool_call"] == tool_call
    assert (tmp_path / "demo.trace.log").exists()


def test_trace_logger_records_tool_error(tmp_path: Path):
    logger = TraceLogger(tmp_path)

    logger.record_tool_call(
        session_id="demo",
        turn_id="turn-1",
        step=1,
        tool_call={"id": "call_bad", "function": {"name": "missing"}},
        execution={
            "tool": "missing",
            "arguments": {},
            "result": {"error": "unknown tool"},
            "error": "unknown tool",
            "tool_call_id": "call_bad",
        },
    )

    record = logger.read_records("demo")[0]

    assert record["tool"] == "missing"
    assert record["error"] == "unknown tool"
    assert record["result"] == {"error": "unknown tool"}


def test_trace_logger_raises_on_damaged_jsonl(tmp_path: Path):
    (tmp_path / "broken.trace.log").write_text("{not-json\n", encoding="utf-8")
    logger = TraceLogger(tmp_path)

    with pytest.raises(TraceError, match="not valid JSONL"):
        logger.read_records("broken")
