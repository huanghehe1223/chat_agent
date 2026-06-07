from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from src.agent.config import load_config
from src.agent.llm import DeepSeekClient
from src.agent.schemas import AssistantMessage
from src.tools.registry import ToolRegistry, build_default_registry


LOG_FILE = Path("logs/deepseek_tool_execution.log")


def write_tool_execution_log(
    test_name: str,
    request: dict,
    message: AssistantMessage,
    execution: dict,
) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "time": datetime.now(timezone.utc).isoformat(),
        "test_name": test_name,
        "request": request,
        "llm_response": {
            "role": message.role,
            "content": message.content,
            "reasoning_content": message.reasoning_content,
            "tool_calls": message.tool_calls,
        },
        "tool_execution": execution,
    }

    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write("\n" + "=" * 100 + "\n")
        f.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        f.write("\n")


def call_llm_and_execute_tool(
    registry: ToolRegistry,
    tool_name: str,
    user_question: str,
) -> tuple[dict, AssistantMessage, dict]:
    config = load_config()
    client = DeepSeekClient(config)
    selected_tools = [
        tool for tool in registry.to_openai_tools() if tool["function"]["name"] == tool_name
    ]
    assert selected_tools
    messages = [
        {
            "role": "system",
            "content": (
                "You are testing native tool calls. Call the provided tool. "
                "Do not answer directly before calling the tool."
            ),
        },
        {"role": "user", "content": user_question},
    ]
    request = {
        "model": config.deepseek_model,
        "messages": messages,
        "tools": selected_tools,
        "max_tokens": 1000,
        "extra_body": {"thinking": {"type": "enabled"}},
    }

    message = client.chat_parsed(
        messages=messages,
        tools=request["tools"],
        max_tokens=request["max_tokens"],
        extra_body=request["extra_body"],
    )
    assert message.tool_calls
    assert message.tool_calls[0]["function"]["name"] == tool_name

    execution = registry.execute_tool_call(message.tool_calls[0])
    return request, message, execution


def test_deepseek_calls_and_executes_calculator_tool(tmp_path: Path):
    registry = build_default_registry(load_config(), todo_store_path=tmp_path / "todos.json")

    request, message, execution = call_llm_and_execute_tool(
        registry=registry,
        tool_name="calculator",
        user_question="请调用 calculator 工具计算 (12 + 8) * 3，参数 expression 必须是这个表达式。",
    )

    write_tool_execution_log(
        "test_deepseek_calls_and_executes_calculator_tool",
        request,
        message,
        execution,
    )

    assert execution["tool"] == "calculator"
    assert execution["result"]["result"] == 60


def test_deepseek_calls_and_executes_todo_tool(tmp_path: Path):
    registry = build_default_registry(load_config(), todo_store_path=tmp_path / "todos.json")

    request, message, execution = call_llm_and_execute_tool(
        registry=registry,
        tool_name="manage_todo_list",
        user_question=(
            "请调用 manage_todo_list 工具提交完整任务列表。参数必须为 "
            'todoList=[{"id":1,"title":"调研最小 Agent runtime","status":"in-progress"}]。'
        ),
    )

    write_tool_execution_log(
        "test_deepseek_calls_and_executes_todo_tool",
        request,
        message,
        execution,
    )

    assert execution["tool"] == "manage_todo_list"
    assert execution["result"]["todoList"][0]["title"] == "调研最小 Agent runtime"
    assert execution["result"]["todoList"][0]["status"] == "in-progress"


def test_deepseek_calls_and_executes_search_tool(tmp_path: Path):
    config = load_config()
    if not config.tavily_api_key:
        pytest.skip("TAVILY_API_KEY is not set; skipping real Tavily search execution.")

    registry = build_default_registry(config, todo_store_path=tmp_path / "todos.json")

    request, message, execution = call_llm_and_execute_tool(
        registry=registry,
        tool_name="search",
        user_question='请调用 search 工具搜索 "DeepSeek API 怎么调用"，max_results 设置为 2。',
    )

    write_tool_execution_log(
        "test_deepseek_calls_and_executes_search_tool",
        request,
        message,
        execution,
    )

    assert execution["tool"] == "search"
    assert execution["result"]["query"]
    assert len(execution["result"]["results"]) >= 1
    assert execution["result"]["results"][0]["url"]
