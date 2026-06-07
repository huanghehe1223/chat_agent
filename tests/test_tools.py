from pathlib import Path

import pytest

from src.agent.config import AgentConfig
from src.tools.calculator import CalculatorError, calculate
from src.tools.registry import ToolRegistryError, build_default_registry
from src.tools.search import tavily_search
from src.tools.todo import TodoError, manage_todo_list


def test_calculator_evaluates_safe_expression():
    result = calculate("(12 + 8) * 3")

    assert result == {
        "expression": "(12 + 8) * 3",
        "result": 60,
    }


def test_calculator_rejects_unsafe_expression():
    with pytest.raises(CalculatorError):
        calculate("__import__('os').system('dir')")


def test_default_registry_exports_openai_tool_schema_and_executes_call(tmp_path: Path):
    registry = build_default_registry(
        AgentConfig(deepseek_api_key="test-key"),
        todo_store_path=tmp_path / "todos.json",
    )

    tools = registry.to_openai_tools()
    tool_names = [tool["function"]["name"] for tool in tools]
    execution = registry.execute_tool_call(
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "calculator",
                "arguments": '{"expression": "(12 + 8) * 3"}',
            },
        }
    )

    assert tool_names == ["calculator", "search", "manage_todo_list"]
    assert execution["tool_call_id"] == "call_1"
    assert execution["tool"] == "calculator"
    assert execution["result"]["result"] == 60


def test_manage_todo_list_schema_requires_full_list_status_updates(tmp_path: Path):
    registry = build_default_registry(
        AgentConfig(deepseek_api_key="test-key"),
        todo_store_path=tmp_path / "todos.json",
    )

    todo_tool = next(
        tool["function"]
        for tool in registry.to_openai_tools()
        if tool["function"]["name"] == "manage_todo_list"
    )
    schema_text = str(todo_tool)

    assert "whenever any task status changes" in todo_tool["description"]
    assert "after finishing a task" in todo_tool["description"]
    assert "Always pass the complete todoList" in todo_tool["description"]
    assert "created, started, or completed" in schema_text
    assert "before the final user-facing answer" in schema_text


def test_search_schema_defines_when_to_use_search(tmp_path: Path):
    registry = build_default_registry(
        AgentConfig(deepseek_api_key="test-key"),
        todo_store_path=tmp_path / "todos.json",
    )

    search_tool = next(
        tool["function"]
        for tool in registry.to_openai_tools()
        if tool["function"]["name"] == "search"
    )
    schema_text = str(search_tool)

    assert "explicitly asks to search" in search_tool["description"]
    assert "time-sensitive information" in search_tool["description"]
    assert "knowledge is insufficient" in search_tool["description"]
    assert "Do not use search for stable general knowledge" in search_tool["description"]
    assert "Include dates, names, products" in schema_text


def test_registry_rejects_unknown_tool(tmp_path: Path):
    registry = build_default_registry(
        AgentConfig(deepseek_api_key="test-key"),
        todo_store_path=tmp_path / "todos.json",
    )

    with pytest.raises(ToolRegistryError, match="unknown tool"):
        registry.execute("missing_tool", {})


def test_manage_todo_list_validates_complete_list():
    result = manage_todo_list(
        [
            {"id": 2, "title": "实现 CLI", "status": "not-started"},
            {"id": 1, "title": "实现 runtime", "status": "in-progress"},
        ]
    )

    assert result["todoList"] == [
        {"id": 1, "title": "实现 runtime", "status": "in-progress"},
        {"id": 2, "title": "实现 CLI", "status": "not-started"},
    ]
    assert result["summary"] == {
        "total": 2,
        "not_started": 1,
        "in_progress": 1,
        "completed": 0,
    }


def test_manage_todo_list_rejects_multiple_in_progress_items():
    with pytest.raises(TodoError, match="only one"):
        manage_todo_list(
            [
                {"id": 1, "title": "one", "status": "in-progress"},
                {"id": 2, "title": "two", "status": "in-progress"},
            ]
        )


def test_tavily_search_formats_results(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "answer": "Tavily answer",
                "results": [
                    {
                        "title": "DeepSeek API Docs",
                        "url": "https://example.com/deepseek",
                        "content": "API usage summary",
                    }
                ],
            }

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("src.tools.search.requests.post", fake_post)

    result = tavily_search("DeepSeek API 怎么调用", max_results=2, api_key="tvly-test", timeout=5)

    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["json"]["api_key"] == "tvly-test"
    assert captured["json"]["max_results"] == 2
    assert result["answer"] == "Tavily answer"
    assert result["results"][0]["title"] == "DeepSeek API Docs"
