"""Streamlit web UI for the agent."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent.memory import SessionMemoryStore
from src.agent.runtime import AgentRuntime, resolve_session_id
from src.agent.trace import TraceLogger


SESSION_DIR = Path("data/sessions")
TRACE_DIR = Path("data/traces")
SYSTEM_AVATAR = ":material/settings:"


def main() -> None:
    try:
        import streamlit as st
    except ImportError as exc:
        raise RuntimeError("Please install dependencies with: pip install -r requirements.txt") from exc

    st.set_page_config(page_title="Minimal Agent", layout="wide")
    _inject_css(st)

    runtime = _get_runtime()
    _init_state(st)

    selected_session = _render_sidebar(st, runtime)
    session = runtime.memory_store.load(selected_session)

    st.title("Minimal Agent")
    st.caption(f"session: `{selected_session}`")

    conversation_tab, trace_tab, req_res_tab = st.tabs(["对话", "工具 Trace", "Req/Res"])
    with conversation_tab:
        _render_messages(st, session.get("messages", []))
        live_area = st.container()
        user_input = st.chat_input("输入消息，工具调用和多轮上下文会自动处理")
        if user_input:
            _run_web_turn(st, runtime, selected_session, user_input, live_area)

    with trace_tab:
        _render_trace_records(st, TraceLogger(TRACE_DIR).read_records(selected_session))

    with req_res_tab:
        _render_req_res_log(st, SESSION_DIR / f"{selected_session}.req_res.log")


def list_session_ids(session_dir: Path = SESSION_DIR) -> list[str]:
    if not session_dir.exists():
        return []
    return sorted(path.stem for path in session_dir.glob("*.json"))


def format_tool_call(tool_call: dict[str, Any]) -> str:
    function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
    if not isinstance(function, dict):
        function = {}
    name = function.get("name", "unknown")
    arguments = function.get("arguments", "")
    tool_call_id = tool_call.get("id", "")
    return f"{name} ({tool_call_id})\n\n```json\n{_pretty_json(arguments)}\n```"


def format_task_list(todo_list: list[dict[str, Any]]) -> list[str]:
    return [
        f"{item.get('id')}. [{item.get('status')}] {item.get('title')}"
        for item in todo_list
    ]


def parse_log_blocks(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    blocks = []
    for block in path.read_text(encoding="utf-8").split("=" * 100):
        block = block.strip()
        if not block:
            continue
        try:
            blocks.append(json.loads(block))
        except json.JSONDecodeError:
            blocks.append({"raw": block})
    return blocks


def read_last_log_block(path: Path) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    blocks = [block.strip() for block in text.split("=" * 100) if block.strip()]
    return blocks[-1] if blocks else ""


def _get_runtime() -> AgentRuntime:
    import streamlit as st

    if "runtime" not in st.session_state:
        st.session_state.runtime = AgentRuntime()
    return st.session_state.runtime


def _init_state(st) -> None:
    if "session_id" not in st.session_state:
        sessions = list_session_ids()
        st.session_state.session_id = sessions[-1] if sessions else resolve_session_id("")


def _render_sidebar(st, runtime: AgentRuntime) -> str:
    st.sidebar.header("Session")
    current = st.session_state.session_id
    ensure_session_exists(runtime, current)
    sessions = list_session_ids()
    if sessions:
        selected = st.sidebar.selectbox(
            "打开会话",
            sessions,
            index=sessions.index(current) if current in sessions else len(sessions) - 1,
        )
        if selected != current:
            st.session_state.session_id = selected
            st.rerun()

    manual_session = st.sidebar.text_input("session_id", value=st.session_state.session_id)
    col_open, col_new = st.sidebar.columns(2)
    if col_open.button("打开", use_container_width=True):
        session_id = resolve_session_id(manual_session)
        ensure_session_exists(runtime, session_id)
        st.session_state.session_id = session_id
        st.rerun()
    if col_new.button("新建", use_container_width=True):
        session_id = resolve_session_id("")
        ensure_session_exists(runtime, session_id)
        st.session_state.session_id = session_id
        st.rerun()

    session_id = st.session_state.session_id
    st.sidebar.divider()
    _render_task_panel(st.sidebar, runtime.memory_store.get_todo_list(session_id))
    st.sidebar.divider()
    trace_records = TraceLogger(TRACE_DIR).read_records(session_id)
    st.sidebar.subheader("最近工具调用")
    if trace_records:
        last = trace_records[-1]
        st.sidebar.caption(f"{last.get('tool')} · step {last.get('step')}")
        st.sidebar.code(_compact_json(last.get("arguments", {})), language="json")
    else:
        st.sidebar.caption("暂无工具调用")
    return session_id


def ensure_session_exists(runtime: AgentRuntime, session_id: str) -> None:
    session = runtime.memory_store.load(session_id)
    runtime.memory_store.save(session)


def _render_task_panel(container, todo_list: list[dict[str, Any]]) -> None:
    container.subheader("Task List")
    if not todo_list:
        container.caption("暂无任务")
        return

    status_icon = {
        "not-started": "○",
        "in-progress": "◐",
        "completed": "●",
    }
    for line, item in zip(format_task_list(todo_list), todo_list):
        container.markdown(f"{status_icon.get(item.get('status'), '-')} `{line}`")


def _render_messages(st, messages: list[dict[str, Any]]) -> None:
    if not messages:
        st.info("当前会话还没有消息。")
        return

    for message in messages:
        role = message.get("role")
        if role == "user":
            with st.chat_message("user"):
                st.markdown(message.get("content", ""))
        elif role == "assistant":
            with st.chat_message("assistant"):
                reasoning = message.get("reasoning_content")
                if reasoning:
                    with st.expander("reasoning", expanded=False):
                        st.markdown(reasoning)
                if message.get("tool_calls"):
                    with st.expander("tool_use", expanded=True):
                        for tool_call in message["tool_calls"]:
                            st.markdown(format_tool_call(tool_call))
                if message.get("content"):
                    st.markdown(message["content"])
        elif role == "tool":
            with st.chat_message("assistant", avatar=SYSTEM_AVATAR):
                with st.expander(f"tool_result · {message.get('name', 'unknown')}", expanded=True):
                    st.code(message.get("content", ""), language="json")


def _run_web_turn(st, runtime: AgentRuntime, session_id: str, user_input: str, live_area) -> None:
    with live_area:
        with st.chat_message("user"):
            st.markdown(user_input)
        task_placeholder = st.sidebar.empty()
        live_state: dict[str, Any] = {}

        def ensure_assistant_block() -> dict[str, Any]:
            if live_state.get("block") is None:
                chat = st.chat_message("assistant")
                with chat:
                    reasoning_expander = st.expander("reasoning", expanded=True)
                    live_state["block"] = {
                        "reasoning_parts": [],
                        "answer_parts": [],
                        "tool_lines": [],
                        "reasoning_placeholder": reasoning_expander.empty(),
                        "tool_placeholder": st.empty(),
                        "answer_placeholder": st.empty(),
                    }
            return live_state["block"]

        def close_assistant_block() -> None:
            live_state["block"] = None

        def render_tool_result(execution: dict[str, Any]) -> None:
            with st.chat_message("assistant", avatar=SYSTEM_AVATAR):
                with st.expander(f"tool_result · {execution.get('tool', 'unknown')}", expanded=True):
                    st.code(_compact_json(execution.get("result")), language="json")

        def on_event(event: dict[str, Any]) -> None:
            event_type = event.get("type")
            if event_type == "reasoning_delta":
                block = ensure_assistant_block()
                block["reasoning_parts"].append(event.get("delta", ""))
                block["reasoning_placeholder"].markdown("".join(block["reasoning_parts"]))
            elif event_type == "content_delta":
                block = ensure_assistant_block()
                block["answer_parts"].append(event.get("delta", ""))
                block["answer_placeholder"].markdown("".join(block["answer_parts"]))
            elif event_type == "tool_call":
                block = ensure_assistant_block()
                block["tool_lines"].append(format_tool_call(event.get("tool_call", {})))
                block["tool_placeholder"].markdown("\n\n".join(block["tool_lines"]))
            elif event_type == "tool_result":
                close_assistant_block()
                render_tool_result(event.get("execution", {}))
            elif event_type == "task_list":
                with task_placeholder.container():
                    _render_task_panel(st, event.get("todoList", []))
            elif event_type == "message":
                close_assistant_block()

        runtime.run_turn(user_input=user_input, session_id=session_id, on_event=on_event)
        st.rerun()


def _render_trace_records(st, records: list[dict[str, Any]]) -> None:
    if not records:
        st.info("当前会话暂无工具 trace。")
        return

    for record in reversed(records[-20:]):
        title = f"{record.get('tool')} · step {record.get('step')} · {record.get('timestamp')}"
        with st.expander(title, expanded=False):
            st.json(record)


def _render_req_res_log(st, path: Path) -> None:
    if not path.exists():
        st.info("当前会话暂无 req/res 日志。")
        return

    st.warning("Req/Res 日志可能很大。为保证页面流畅，默认不读取；需要排查时再手动加载。")
    st.caption(f"日志文件：{path}")
    if not st.checkbox("加载最近一段原始 Req/Res 日志", value=False):
        return

    raw_block = read_last_log_block(path)
    if not raw_block:
        st.info("日志为空。")
        return
    st.code(raw_block, language="json")


def _pretty_json(value: Any) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _inject_css(st) -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.5rem; max-width: 1180px; }
        section[data-testid="stSidebar"] { min-width: 310px; }
        div[data-testid="stChatMessage"] { border-radius: 6px; padding: 0.25rem 0; }
        code { white-space: pre-wrap !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
