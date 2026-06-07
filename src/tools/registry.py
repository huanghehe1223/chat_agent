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
            description="Calculate a simple arithmetic expression using numbers, operators, and parentheses.",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Arithmetic expression, for example: (12 + 8) * 3.",
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
            description="Search the web with Tavily and return titles, URLs, and summaries.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query keywords.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Number of results to return, from 1 to 5.",
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
                "Use this for complex multi-step work, after receiving multiple tasks, before "
                "starting a todo, and immediately after completing a todo. Always pass the "
                "complete todoList, including all existing and new items. Do not call this for "
                "single trivial tasks or pure conversation. Todo states: not-started, "
                "in-progress (at most one item), completed."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "todoList": {
                        "type": "array",
                        "description": "Complete array of all todo items. Must include ALL items - both existing and new.",
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
                                        "(max 1) | completed: fully finished"
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
