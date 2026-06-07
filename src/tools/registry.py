"""Tool registry and OpenAI-compatible tool-call execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.agent.config import AgentConfig
from src.tools.calculator import calculate
from src.tools.search import tavily_search
from src.tools.todo import manage_todo_list


class ToolRegistryError(RuntimeError):
    """Raised when a tool cannot be registered or executed."""


ToolHandler = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry that owns tool schemas and local execution handlers."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ToolRegistryError(f"tool already registered: {definition.name}")
        self._tools[definition.name] = definition

    def to_openai_tools(self) -> list[dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self._tools.values()]

    def execute(self, name: str, arguments: str | dict[str, Any] | None = None) -> dict[str, Any]:
        definition = self._tools.get(name)
        if definition is None:
            raise ToolRegistryError(f"unknown tool: {name}")

        parsed_arguments = self._parse_arguments(arguments)
        try:
            result = definition.handler(**parsed_arguments)
        except TypeError as exc:
            raise ToolRegistryError(f"invalid arguments for tool {name}: {parsed_arguments}") from exc

        return {
            "tool": name,
            "arguments": parsed_arguments,
            "result": result,
        }

    def execute_tool_call(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        function = tool_call.get("function")
        if not isinstance(function, dict):
            raise ToolRegistryError("tool_call missing function object.")

        name = function.get("name")
        if not isinstance(name, str) or not name:
            raise ToolRegistryError("tool_call function missing name.")

        execution = self.execute(name, function.get("arguments"))
        execution["tool_call_id"] = tool_call.get("id", "")
        execution["type"] = tool_call.get("type", "function")
        return execution

    @staticmethod
    def _parse_arguments(arguments: str | dict[str, Any] | None) -> dict[str, Any]:
        if arguments is None or arguments == "":
            return {}
        if isinstance(arguments, dict):
            return arguments
        if not isinstance(arguments, str):
            raise ToolRegistryError("tool arguments must be a JSON string or object.")

        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise ToolRegistryError("tool arguments must be valid JSON.") from exc

        if not isinstance(parsed, dict):
            raise ToolRegistryError("tool arguments must decode to an object.")
        return parsed


def build_default_registry(
    config: AgentConfig,
    todo_store_path: str | Path = "data/sessions/todo_tasks.json",
) -> ToolRegistry:
    """Create the three required project tools."""

    registry = ToolRegistry()

    registry.register(
        ToolDefinition(
            name="calculator",
            description=(
                "Calculate a math expression safely. Supports arithmetic operators "
                "+, -, *, /, //, %, **, parentheses, constants pi/e/tau, and common "
                "functions such as sqrt, sin, cos, tan, log, log10, abs, min, max, round."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": (
                            "Math expression, for example: (12 + 8) * 3, sqrt(144), "
                            "sin(pi / 2), log(100, 10), or max(2, 8, 5)."
                        ),
                    }
                },
                "required": ["expression"],
            },
            handler=calculate,
        )
    )
    registry.register(
        ToolDefinition(
            name="search",
            description=(
                "Search the web with Tavily and return titles, URLs, and summaries. "
                "Use this tool when the user explicitly asks to search/look up/check online, "
                "when the question depends on current or time-sensitive information, or when "
                "your own knowledge is insufficient to answer reliably. Do not use search for "
                "stable general knowledge, simple calculations, pure conversation, or questions "
                "that can be answered confidently from existing context."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Focused search query keywords. Include dates, names, products, "
                            "locations, or other concrete constraints when recency or precision matters."
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Number of results to return, from 1 to 5. Use 3 by default unless the user needs broader coverage.",
                        "minimum": 1,
                        "maximum": 5,
                    },
                },
                "required": ["query"],
            },
            handler=lambda query, max_results=3: tavily_search(
                query=query,
                max_results=max_results,
                api_key=config.tavily_api_key,
                timeout=config.request_timeout,
            ),
        )
    )
    registry.register(
        ToolDefinition(
            name="manage_todo_list",
            description=(
                "Manage the complete session todo list for planning and progress tracking. "
                "Call this tool whenever the user asks to create a task list or gives complex "
                "multi-step work. You must also call it immediately whenever any task status "
                "changes: before starting a task, submit the full list with exactly that task "
                "marked in-progress; after finishing a task, submit the full list again with "
                "that task marked completed before giving the final answer or moving on. "
                "Always pass the complete todoList, including all existing and new items; never "
                "send only the changed item. Do not call this for single trivial tasks or pure "
                "conversation. Todo states: not-started, in-progress (at most one item), completed."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "todoList": {
                        "type": "array",
                        "description": (
                            "Complete array of all session todo items after this update. Must "
                            "include ALL items - both existing and new - every time a task is "
                            "created, started, or completed. Status updates must be committed "
                            "through this full-list snapshot before the final user-facing answer."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "number",
                                    "description": "Unique identifier for the todo. Use sequential numbers starting from 1.",
                                },
                                "title": {
                                    "type": "string",
                                    "description": "Concise action-oriented todo label.",
                                },
                                "status": {
                                    "type": "string",
                                    "enum": ["not-started", "in-progress", "completed"],
                                    "description": (
                                        "not-started: not begun | in-progress: currently working "
                                        "(max 1) | completed: fully finished and already reflected "
                                        "in the submitted full todoList"
                                    ),
                                },
                            },
                            "required": ["id", "title", "status"],
                        },
                    }
                },
                "required": ["todoList"],
            },
            handler=manage_todo_list,
        )
    )
    return registry
