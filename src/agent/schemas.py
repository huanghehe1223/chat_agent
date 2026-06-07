"""Shared data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AssistantMessage:
    """Parsed assistant message returned by the LLM API."""

    role: str
    content: str = ""
    reasoning_content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @classmethod
    def from_api_message(cls, message: dict[str, Any]) -> "AssistantMessage":
        content = message.get("content") or ""
        reasoning_content = message.get("reasoning_content") or ""
        tool_calls = message.get("tool_calls") or []

        return cls(
            role=message.get("role", ""),
            content=content,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
            raw=message,
        )

    def to_openai_message(self) -> dict[str, Any]:
        """Return the assistant message shape expected in chat history."""

        message: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
        }
        if self.reasoning_content:
            message["reasoning_content"] = self.reasoning_content
        if self.tool_calls:
            message["tool_calls"] = self.tool_calls
        return message
