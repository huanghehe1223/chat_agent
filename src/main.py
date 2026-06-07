"""Command line entrypoint for the agent."""

from __future__ import annotations

import argparse
import json
from typing import Any

from src.agent.runtime import AgentRuntime, resolve_session_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the minimal DeepSeek tool agent.")
    parser.add_argument(
        "--session",
        default="",
        help="Session id to read/write. Leave empty to create a timestamp+uuid session.",
    )
    parser.add_argument(
        "--debug",
        dest="debug",
        action="store_true",
        default=True,
        help="Print reasoning and tool stream events. Enabled by default.",
    )
    parser.add_argument("--no-debug", dest="debug", action="store_false", help="Hide reasoning/tool debug events.")
    parser.add_argument("--once", help="Run a single user message and exit.")
    args = parser.parse_args()

    runtime = AgentRuntime()
    session_id = resolve_session_id(args.session)
    if not args.session.strip():
        print(f"Created session: {session_id}")

    _print_recent_context(runtime, session_id)
    _print_task_list(runtime.memory_store.get_todo_list(session_id))
    if args.once:
        _run_once(runtime, session_id, args.once, args.debug)
        return

    print(f"Agent CLI started. session={session_id}. Type exit/quit to stop.")
    while True:
        try:
            user_input = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "q"}:
            print("Bye.")
            return

        _run_once(runtime, session_id, user_input, args.debug)


def _run_once(runtime: AgentRuntime, session_id: str, user_input: str, debug: bool) -> None:
    printed_content = False
    reasoning_open = False

    def close_reasoning() -> None:
        nonlocal reasoning_open
        if reasoning_open:
            print("\n[/reasoning]")
            reasoning_open = False

    def on_event(event: dict[str, Any]) -> None:
        nonlocal printed_content, reasoning_open
        event_type = event.get("type")
        if event_type == "content_delta":
            close_reasoning()
            print(event.get("delta", ""), end="", flush=True)
            printed_content = True
        elif debug and event_type == "reasoning_delta":
            if not reasoning_open:
                print("\n[reasoning]")
                reasoning_open = True
            print(event.get("delta", ""), end="", flush=True)
        elif debug and event_type == "tool_call":
            close_reasoning()
            tool_call = event.get("tool_call", {})
            function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
            print(f"\n[tool_call] {function.get('name', 'unknown')} {function.get('arguments', '')}")
        elif debug and event_type == "tool_result":
            close_reasoning()
            execution = event.get("execution", {})
            print(f"\n[tool_result] {execution.get('tool', 'unknown')} -> {execution.get('result')}")
        elif event_type == "task_list":
            close_reasoning()
            _print_task_list(event.get("todoList", []))
        elif event_type == "message":
            close_reasoning()

    print("Agent> ", end="", flush=True)
    result = runtime.run_turn(user_input=user_input, session_id=session_id, on_event=on_event)
    close_reasoning()
    if not printed_content and result.answer:
        print(result.answer, end="")
    print()


def _print_recent_context(runtime: AgentRuntime, session_id: str, limit: int = 5) -> None:
    session = runtime.memory_store.load(session_id)
    messages = session.get("messages", [])
    if not messages:
        return

    print(f"Recent context for session={session_id} (last {min(limit, len(messages))} messages):")
    for index, message in enumerate(messages[-limit:], start=1):
        print(f"{index}. {_format_context_message(message)}")
    print()


def _print_task_list(todo_list: list[dict[str, Any]]) -> None:
    if not todo_list:
        return

    print("\n[todo_list]")
    for item in todo_list:
        print(f"- {item.get('id')}. [{item.get('status')}] {item.get('title')}")
    print("[/todo_list]")


def _format_context_message(message: dict[str, Any]) -> str:
    role = message.get("role")
    if role == "user":
        return f"[user_prompt] {message.get('content', '')}"

    if role == "assistant":
        parts = []
        reasoning = message.get("reasoning_content")
        if reasoning:
            parts.append(f"[reasoning]\n{reasoning}\n[/reasoning]")
        if message.get("tool_calls"):
            for tool_call in message["tool_calls"]:
                parts.append(_format_tool_call(tool_call))
        content = message.get("content")
        if content:
            parts.append(f"[assistant_response] {content}")
        return "\n".join(parts) if parts else "[assistant_response]"

    if role == "tool":
        return (
            f"[tool_result] {message.get('name', 'unknown')} "
            f"({message.get('tool_call_id', '')}) -> {message.get('content', '')}"
        )

    return f"[{role or 'unknown'}] {json.dumps(message, ensure_ascii=False, default=str)}"


def _format_tool_call(tool_call: dict[str, Any]) -> str:
    function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
    if not isinstance(function, dict):
        function = {}
    return (
        f"[tool_call] {function.get('name', 'unknown')} "
        f"({tool_call.get('id', '')}) {function.get('arguments', '')}"
    )


if __name__ == "__main__":
    main()
