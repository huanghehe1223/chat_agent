"""Session memory and LLM context assembly."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.agent.schemas import AssistantMessage


class MemoryError(RuntimeError):
    """Raised when session memory cannot be loaded or saved."""


_FORBIDDEN_SESSION_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class SessionMemoryStore:
    """JSON-backed session store.

    Local session messages keep debugging fields such as ``reasoning_content``.
    Requests sent back to the LLM must be built through ``build_llm_context``.
    """

    root_dir: Path = Path("data/sessions")

    def __post_init__(self) -> None:
        self.root_dir = Path(self.root_dir)

    def load(self, session_id: str = "default") -> dict[str, Any]:
        path = self._session_path(session_id)
        if not path.exists():
            return _new_session(session_id)

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise MemoryError(f"session file is not valid JSON: {path}") from exc

        return _validate_session(data, session_id)

    def save(self, session: dict[str, Any]) -> dict[str, Any]:
        session_id = _validate_session_id(str(session.get("session_id", "")))
        now = _now()
        session.setdefault("metadata", {})
        session["metadata"].setdefault("created_at", now)
        session["metadata"]["updated_at"] = now

        data = _validate_session(session, session_id)
        path = self._session_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    def append_user_message(self, session_id: str, content: str) -> dict[str, Any]:
        session = self.load(session_id)
        session["messages"].append(
            {
                "role": "user",
                "content": _require_text(content, "content"),
                "metadata": {
                    "created_at": _now(),
                    "message_type": "user_message",
                },
            }
        )
        return self.save(session)

    def append_assistant_message(
        self,
        session_id: str,
        message: AssistantMessage | dict[str, Any],
    ) -> dict[str, Any]:
        session = self.load(session_id)
        api_message = message.to_openai_message() if isinstance(message, AssistantMessage) else message
        local_message: dict[str, Any] = {
            "role": "assistant",
            "content": api_message.get("content") or "",
            "metadata": {
                "created_at": _now(),
                "message_type": "assistant_response",
            },
        }
        if api_message.get("reasoning_content"):
            local_message["reasoning_content"] = api_message["reasoning_content"]
        if api_message.get("tool_calls"):
            local_message["tool_calls"] = api_message["tool_calls"]
            local_message["metadata"]["message_type"] = "assistant_tool_calls"

        session["messages"].append(local_message)
        return self.save(session)

    def append_tool_message(
        self,
        session_id: str,
        tool_call_id: str,
        name: str,
        result: Any,
    ) -> dict[str, Any]:
        session = self.load(session_id)
        session["messages"].append(
            {
                "role": "tool",
                "tool_call_id": _require_text(tool_call_id, "tool_call_id"),
                "name": _require_text(name, "name"),
                "content": json.dumps(result, ensure_ascii=False, default=str),
                "metadata": {
                    "created_at": _now(),
                    "message_type": "tool_result",
                },
            }
        )
        return self.save(session)

    def set_task(self, session_id: str, task: dict[str, Any]) -> dict[str, Any]:
        task_id = _require_text(str(task.get("id", "")), "task.id")
        session = self.load(session_id)
        stored_task = deepcopy(task)
        stored_task["updated_at"] = stored_task.get("updated_at") or _now()
        session["memory"]["tasks"][task_id] = stored_task
        return self.save(session)

    def set_todo_list(self, session_id: str, todo_list: list[dict[str, Any]]) -> dict[str, Any]:
        session = self.load(session_id)
        now = _now()
        tasks: dict[str, dict[str, Any]] = {}
        for item in todo_list:
            task_id = str(item.get("id", ""))
            stored_task = deepcopy(item)
            stored_task["updated_at"] = now
            tasks[task_id] = stored_task
        session["memory"]["tasks"] = tasks
        return self.save(session)

    def get_todo_list(self, session_id: str) -> list[dict[str, Any]]:
        session = self.load(session_id)
        tasks = session["memory"]["tasks"].values()
        return sorted((deepcopy(task) for task in tasks), key=lambda task: int(task.get("id", 0)))

    def _session_path(self, session_id: str) -> Path:
        safe_session_id = _validate_session_id(session_id)
        return self.root_dir / f"{safe_session_id}.json"


def build_llm_context(
    session: dict[str, Any],
    system_prompt: str | None = None,
    max_messages: int | None = None,
) -> list[dict[str, Any]]:
    """Build an LLM request context from local session data.

    This intentionally filters local-only fields such as ``reasoning_content``
    and message metadata.
    """

    data = _validate_session(session, str(session.get("session_id", "")))
    context: list[dict[str, Any]] = []

    system_parts = []
    if system_prompt:
        system_parts.append(system_prompt.strip())
    memory_summary = build_memory_summary(data.get("memory", {}))
    if memory_summary:
        system_parts.append(memory_summary)
    if system_parts:
        context.append({"role": "system", "content": "\n\n".join(system_parts)})

    messages = data["messages"]
    if max_messages is not None:
        messages = messages[-max_messages:]

    for message in messages:
        converted = _to_llm_message(message)
        if converted is not None:
            context.append(converted)

    return context


def build_memory_summary(memory: dict[str, Any]) -> str:
    tasks = memory.get("tasks") or {}
    if not tasks:
        return ""

    lines = ["当前 session 任务状态："]
    task_items = tasks.values() if isinstance(tasks, dict) else tasks
    for task in task_items:
        if not isinstance(task, dict):
            continue
        title = task.get("title", "")
        status = task.get("status", "")
        task_id = task.get("id", "")
        if title:
            lines.append(f"- [{status}] {title} (id: {task_id})")
    return "\n".join(lines) if len(lines) > 1 else ""


def _to_llm_message(message: dict[str, Any]) -> dict[str, Any] | None:
    role = message.get("role")
    if role == "user":
        return {"role": "user", "content": message.get("content") or ""}

    if role == "assistant":
        llm_message: dict[str, Any] = {
            "role": "assistant",
            "content": message.get("content") or "",
        }
        if message.get("tool_calls"):
            llm_message["tool_calls"] = deepcopy(message["tool_calls"])
        return llm_message

    if role == "tool":
        return {
            "role": "tool",
            "tool_call_id": message.get("tool_call_id", ""),
            "name": message.get("name", ""),
            "content": message.get("content") or "",
        }

    return None


def _new_session(session_id: str) -> dict[str, Any]:
    safe_session_id = _validate_session_id(session_id)
    now = _now()
    return {
        "session_id": safe_session_id,
        "messages": [],
        "memory": {
            "tasks": {},
            "facts": {},
            "preferences": {},
        },
        "metadata": {
            "created_at": now,
            "updated_at": now,
        },
    }


def _validate_session(data: dict[str, Any], expected_session_id: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise MemoryError("session data must be an object.")

    session_id = _validate_session_id(str(data.get("session_id") or expected_session_id))
    session = deepcopy(data)
    session["session_id"] = session_id

    if not isinstance(session.get("messages"), list):
        raise MemoryError("session messages must be a list.")

    memory = session.setdefault("memory", {})
    if not isinstance(memory, dict):
        raise MemoryError("session memory must be an object.")
    for key in ["tasks", "facts", "preferences"]:
        value = memory.setdefault(key, {})
        if not isinstance(value, dict):
            raise MemoryError(f"session memory.{key} must be an object.")

    metadata = session.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        raise MemoryError("session metadata must be an object.")
    now = _now()
    metadata.setdefault("created_at", now)
    metadata.setdefault("updated_at", now)

    return session


def _validate_session_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not session_id.strip():
        raise MemoryError("session_id must be a non-empty string.")
    safe_session_id = session_id.strip()
    if safe_session_id in {".", ".."} or ".." in safe_session_id:
        raise MemoryError("session_id must not contain path traversal segments.")
    if _FORBIDDEN_SESSION_CHARS.search(safe_session_id):
        raise MemoryError('session_id must not contain path separators or Windows reserved characters: <>:"/\\|?*')
    return safe_session_id


def _require_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MemoryError(f"{name} must be a non-empty string.")
    return value.strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
