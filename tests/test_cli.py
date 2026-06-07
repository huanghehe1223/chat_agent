from types import SimpleNamespace

from src.agent.runtime import AgentTurnResult
from src.main import _print_recent_context, _run_once


class FakeMemoryStore:
    def __init__(self, messages, todo_list=None):
        self.messages = messages
        self.todo_list = todo_list or []

    def load(self, session_id):
        return {
            "session_id": session_id,
            "messages": self.messages,
            "memory": {"tasks": {}, "facts": {}, "preferences": {}},
            "metadata": {},
        }

    def get_todo_list(self, session_id):
        return self.todo_list


class FakeRuntime:
    def __init__(self):
        self.memory_store = FakeMemoryStore([])

    def run_turn(self, user_input, session_id="default", on_event=None):
        on_event({"type": "reasoning_delta", "delta": "Think "})
        on_event({"type": "reasoning_delta", "delta": "briefly."})
        on_event(
            {
                "type": "task_list",
                "todoList": [{"id": 1, "title": "实现 runtime", "status": "in-progress"}],
            }
        )
        on_event({"type": "content_delta", "delta": "OK"})
        on_event({"type": "message", "message": {"role": "assistant", "content": "OK"}})
        return AgentTurnResult(session_id=session_id, turn_id="turn-1", answer="OK")


def test_run_once_wraps_reasoning_as_one_block(capsys):
    _run_once(FakeRuntime(), "demo", "ping", debug=True)

    output = capsys.readouterr().out

    assert output.count("[reasoning]") == 1
    assert output.count("[/reasoning]") == 1
    assert "[reasoning]\nThink briefly.\n[/reasoning]" in output
    assert output.rstrip().endswith("OK")
    assert "[todo_list]" in output
    assert "- 1. [in-progress] 实现 runtime" in output


def test_print_recent_context_formats_last_five_messages(capsys):
    messages = [
        {"role": "user", "content": "old"},
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": "I will calculate.",
            "reasoning_content": "Need calculator.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "calculator",
                        "arguments": '{"expression": "1 + 1"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "calculator",
            "content": '{"result": 2}',
        },
        {"role": "assistant", "content": "2"},
        {"role": "user", "content": "thanks"},
    ]
    runtime = SimpleNamespace(memory_store=FakeMemoryStore(messages))

    _print_recent_context(runtime, "demo")

    output = capsys.readouterr().out

    assert "old" not in output
    assert "[user_prompt] hello" in output
    assert "[reasoning]\nNeed calculator.\n[/reasoning]" in output
    assert '[tool_call] calculator (call_1) {"expression": "1 + 1"}' in output
    assert '[tool_result] calculator (call_1) -> {"result": 2}' in output
    assert "[assistant_response] 2" in output


def test_print_task_list_on_session_start(capsys):
    runtime = SimpleNamespace(
        memory_store=FakeMemoryStore(
            [],
            todo_list=[
                {"id": 1, "title": "实现 runtime", "status": "completed"},
                {"id": 2, "title": "完善 CLI", "status": "in-progress"},
            ],
        )
    )

    from src.main import _print_task_list

    _print_task_list(runtime.memory_store.get_todo_list("demo"))

    output = capsys.readouterr().out

    assert "[todo_list]" in output
    assert "- 1. [completed] 实现 runtime" in output
    assert "- 2. [in-progress] 完善 CLI" in output
