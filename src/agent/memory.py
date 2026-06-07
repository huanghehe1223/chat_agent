"""Session memory and LLM context assembly."""

from __future__ import annotations

import json
import re
import threading
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.agent.schemas import AssistantMessage


class MemoryError(RuntimeError):
    """Raised when session memory cannot be loaded or saved."""


_FORBIDDEN_SESSION_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
DEFAULT_SESSION_NAME = "New Chat"
SESSION_NAME_SOURCE_DEFAULT = "default"
SESSION_NAME_SOURCE_GENERATED = "generated"
SESSION_NAME_SOURCE_USER = "user"


@dataclass
class SessionMemoryStore:
    """JSON-backed session store.

    Local session messages keep debugging fields such as ``reasoning_content``.
    Requests sent back to the LLM must be built through ``build_llm_context``.
    """

    root_dir: Path = Path("data/sessions")

    def __post_init__(self) -> None:
        self.root_dir = Path(self.root_dir)
        self._lock = threading.RLock()

    def load(self, session_id: str = "default") -> dict[str, Any]:
        with self._lock:
            path = self._session_path(session_id)
            if not path.exists():
                return _new_session(session_id)

            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise MemoryError(f"session file is not valid JSON: {path}") from exc

            return _validate_session(data, session_id)

    def create(self, session_name: str | None = None, session_id: str | None = None) -> dict[str, Any]:
        """Create a new session with a UUID id and a display name.

        ``session_id`` is the storage locator and JSON filename. ``session_name``
        is user-facing metadata and may be duplicated across sessions.
        """

        with self._lock:
            safe_session_id = _validate_session_id(session_id or new_session_id())
            path = self._session_path(safe_session_id)
            if path.exists():
                raise MemoryError(f"session already exists: {safe_session_id}")
            name_source = SESSION_NAME_SOURCE_USER if isinstance(session_name, str) and session_name.strip() else SESSION_NAME_SOURCE_DEFAULT
            return self.save(_new_session(safe_session_id, session_name=session_name, name_source=name_source))

    def save(self, session: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            session_id = _validate_session_id(str(session.get("session_id", "")))
            now = _now()
            session.setdefault("metadata", {})
            session["metadata"].setdefault("created_at", now)
            session["metadata"]["updated_at"] = now

            data = _validate_session(session, session_id)
            path = self._session_path(session_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_name(f".{path.stem}.{uuid4().hex}.tmp")
            try:
                temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                temp_path.replace(path)
            finally:
                if temp_path.exists():
                    temp_path.unlink()
            return data

    def append_user_message(self, session_id: str, content: str) -> dict[str, Any]:
        with self._lock:
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
        with self._lock:
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
        with self._lock:
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
        with self._lock:
            task_id = _require_text(str(task.get("id", "")), "task.id")
            session = self.load(session_id)
            stored_task = deepcopy(task)
            stored_task["updated_at"] = stored_task.get("updated_at") or _now()
            session["memory"]["tasks"][task_id] = stored_task
            return self.save(session)

    def set_todo_list(self, session_id: str, todo_list: list[dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
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

    def update_session_name(
        self,
        session_id: str,
        session_name: str,
        source: str = SESSION_NAME_SOURCE_GENERATED,
    ) -> dict[str, Any]:
        with self._lock:
            session = self.load(session_id)
            session["session_name"] = _normalize_session_name(session_name)
            session.setdefault("metadata", {})["session_name_source"] = source
            if source == SESSION_NAME_SOURCE_GENERATED:
                session["metadata"]["title_generated_at"] = _now()
            return self.save(session)

    def find_default_untitled_session(self) -> str | None:
        if not self.root_dir.exists():
            return None

        candidates: list[tuple[str, str]] = []
        for path in self.root_dir.glob("*.json"):
            try:
                session = self.load(path.stem)
            except MemoryError:
                continue
            if is_default_untitled_session(session):
                created_at = str(session.get("metadata", {}).get("created_at", ""))
                candidates.append((created_at, session["session_id"]))
        if not candidates:
            return None
        return sorted(candidates, reverse=True)[0][1]

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
    if len(lines) > 1:
        lines.append(
            "任务状态变更规则：开始或完成任何任务时，必须立即调用 manage_todo_list 提交完整 todoList；"
            "不要只在文字中说明状态变化。"
        )
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


def new_session_id() -> str:
    return str(uuid4())


def is_default_untitled_session(session: dict[str, Any]) -> bool:
    metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    return (
        session.get("session_name") == DEFAULT_SESSION_NAME
        and metadata.get("session_name_source") == SESSION_NAME_SOURCE_DEFAULT
    )


def should_generate_session_title(session: dict[str, Any]) -> bool:
    if not is_default_untitled_session(session):
        return False
    messages = session.get("messages")
    if not isinstance(messages, list):
        return False
    return any(message.get("role") == "user" for message in messages)


def first_user_prompt(session: dict[str, Any]) -> str:
    messages = session.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in messages:
        if message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


def _new_session(
    session_id: str,
    session_name: str | None = None,
    name_source: str = SESSION_NAME_SOURCE_USER,
) -> dict[str, Any]:
    safe_session_id = _validate_session_id(session_id)
    now = _now()
    normalized_name = _normalize_session_name(session_name)
    if name_source == SESSION_NAME_SOURCE_USER and not (isinstance(session_name, str) and session_name.strip()):
        normalized_name = safe_session_id
    return {
        "session_id": safe_session_id,
        "session_name": normalized_name,
        "messages": [],
        "memory": {
            "tasks": {},
            "facts": {},
            "preferences": {},
        },
        "metadata": {
            "created_at": now,
            "updated_at": now,
            "session_name_source": name_source,
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
    metadata.setdefault("session_name_source", SESSION_NAME_SOURCE_USER)
    session["session_name"] = _normalize_session_name(
        session.get("session_name")
        or metadata.get("session_name")
        or session_id
    )
    if (
        session["session_name"] == DEFAULT_SESSION_NAME
        and metadata.get("session_name_source") == SESSION_NAME_SOURCE_GENERATED
    ):
        metadata["session_name_source"] = SESSION_NAME_SOURCE_DEFAULT
        metadata.pop("title_generated_at", None)
        metadata.setdefault("title_generation_error", "generated title was empty or default")

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


def _normalize_session_name(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return DEFAULT_SESSION_NAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
