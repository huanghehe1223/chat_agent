"""Tool-call trace logging."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


class TraceError(RuntimeError):
    """Raised when trace records cannot be read or written."""


@dataclass
class TraceLogger:
    """Append-only tool trace logger.

    Request/response logs capture full LLM calls. Trace logs are a compact
    session-level summary of local tool execution.
    """

    root_dir: Path = Path("data/traces")
    timezone: str = "Asia/Shanghai"

    def __post_init__(self) -> None:
        self.root_dir = Path(self.root_dir)

    def record_tool_call(
        self,
        session_id: str,
        turn_id: str,
        step: int,
        tool_call: dict[str, Any],
        execution: dict[str, Any],
    ) -> dict[str, Any]:
        record = {
            "timestamp": datetime.now(ZoneInfo(self.timezone)).isoformat(),
            "session_id": session_id,
            "turn_id": turn_id,
            "step": step,
            "tool_call_id": execution.get("tool_call_id") or tool_call.get("id", ""),
            "tool": execution.get("tool", _tool_name_from_call(tool_call)),
            "arguments": execution.get("arguments", {}),
            "result": execution.get("result"),
            "error": execution.get("error"),
            "raw_tool_call": tool_call,
        }
        self._append_record(session_id, record)
        return record

    def read_records(self, session_id: str) -> list[dict[str, Any]]:
        path = self._trace_path(session_id)
        if not path.exists():
            return []

        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise TraceError(f"trace file is not valid JSONL: {path}") from exc
        return records

    def _append_record(self, session_id: str, record: dict[str, Any]) -> None:
        path = self._trace_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str))
            f.write("\n")

    def _trace_path(self, session_id: str) -> Path:
        return self.root_dir / f"{session_id}.trace.log"


def _tool_name_from_call(tool_call: dict[str, Any]) -> str:
    function = tool_call.get("function")
    if isinstance(function, dict) and isinstance(function.get("name"), str):
        return function["name"]
    return "unknown"
