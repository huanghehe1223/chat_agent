"""Session todo-list management tool."""

from __future__ import annotations

from typing import Any


class TodoError(ValueError):
    """Raised when a todo list update is invalid."""


VALID_STATUSES = {"not-started", "in-progress", "completed"}


def manage_todo_list(todoList: list[dict[str, Any]]) -> dict[str, Any]:  # noqa: N803 - external schema name
    """Validate and normalize a complete session todo list.

    The model must submit the full list every time. Persistence is handled by
    the runtime because the target storage is session-scoped.
    """

    if not isinstance(todoList, list):
        raise TodoError("todoList must be an array.")

    normalized = [_normalize_item(item) for item in todoList]
    ids = [item["id"] for item in normalized]
    if len(ids) != len(set(ids)):
        raise TodoError("todo ids must be unique.")

    in_progress = [item for item in normalized if item["status"] == "in-progress"]
    if len(in_progress) > 1:
        raise TodoError("only one todo may be in-progress at a time.")

    normalized.sort(key=lambda item: item["id"])
    return {
        "todoList": normalized,
        "summary": {
            "total": len(normalized),
            "not_started": sum(1 for item in normalized if item["status"] == "not-started"),
            "in_progress": sum(1 for item in normalized if item["status"] == "in-progress"),
            "completed": sum(1 for item in normalized if item["status"] == "completed"),
        },
    }


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise TodoError("each todo item must be an object.")

    try:
        item_id = int(item.get("id"))
    except (TypeError, ValueError) as exc:
        raise TodoError("todo id must be a number.") from exc

    if item_id < 1:
        raise TodoError("todo id must be greater than 0.")

    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        raise TodoError("todo title must be a non-empty string.")

    status = item.get("status")
    if status not in VALID_STATUSES:
        raise TodoError("todo status must be not-started, in-progress, or completed.")

    return {
        "id": item_id,
        "title": title.strip(),
        "status": status,
    }
