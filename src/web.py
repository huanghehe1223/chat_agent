"""Streamlit web UI for the agent."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent.memory import DEFAULT_SESSION_NAME, SessionMemoryStore
from src.agent.runtime import AgentRuntime, resolve_session_id
from src.agent.trace import TraceLogger


SESSION_DIR = Path("data/sessions")
TRACE_DIR = Path("data/traces")
SYSTEM_AVATAR = ":material/settings:"
LIVE_AUTO_COLLAPSE_SECONDS = 2.0


def main() -> None:
    try:
        import streamlit as st
    except ImportError as exc:
        raise RuntimeError("Please install dependencies with: pip install -r requirements.txt") from exc

    st.set_page_config(page_title="Minimal Agent", layout="wide")
    _inject_css(st)

    runtime = _get_runtime()
    _init_state(st)

    selected_session, task_panel = _render_sidebar(st, runtime)
    session = runtime.memory_store.load(selected_session)

    st.title("Minimal Agent")
    st.caption(f"session_id: `{selected_session}`")

    conversation_tab, trace_tab, req_res_tab = st.tabs(["对话", "工具 Trace", "Req/Res"])
    with conversation_tab:
        _render_messages(st, session.get("messages", []))
        live_area = st.container()
        user_input = st.chat_input("输入消息，工具调用和多轮上下文会自动处理")
        if user_input:
            _run_web_turn(st, runtime, selected_session, user_input, live_area, task_panel)

    with trace_tab:
        _render_trace_records(st, TraceLogger(TRACE_DIR).read_records(selected_session))

    with req_res_tab:
        _render_req_res_log(st, SESSION_DIR / f"{selected_session}.req_res.log")


def list_session_ids(session_dir: Path = SESSION_DIR) -> list[str]:
    return [session["session_id"] for session in list_session_summaries(session_dir)]


def list_session_summaries(session_dir: Path = SESSION_DIR) -> list[dict[str, str]]:
    if not session_dir.exists():
        return []
    session_paths = list(session_dir.glob("*.json"))
    return [_read_session_summary(path) for path in sorted(session_paths, key=_session_sort_key, reverse=True)]


def _session_sort_key(path: Path) -> tuple[float, str]:
    created_at = _read_session_created_at(path)
    if created_at is not None:
        timestamp = created_at.timestamp()
    else:
        try:
            timestamp = path.stat().st_mtime
        except OSError:
            timestamp = 0
    return (timestamp, path.stem)


def _read_session_created_at(path: Path) -> datetime | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    metadata = data.get("metadata") if isinstance(data, dict) else None
    if not isinstance(metadata, dict):
        return None
    created_at = metadata.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        return None
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _read_session_summary(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}

    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    session_name = data.get("session_name") or metadata.get("session_name") or data.get("session_id") or path.stem
    if not isinstance(session_name, str) or not session_name.strip():
        session_name = DEFAULT_SESSION_NAME

    return {
        "session_id": path.stem,
        "session_name": session_name.strip(),
    }


def format_session_label(summary: dict[str, str]) -> str:
    return summary.get("session_name") or DEFAULT_SESSION_NAME


def build_session_labels(summaries: list[dict[str, str]]) -> dict[str, str]:
    name_counts: dict[str, int] = {}
    for summary in summaries:
        name = summary.get("session_name") or DEFAULT_SESSION_NAME
        name_counts[name] = name_counts.get(name, 0) + 1

    labels: dict[str, str] = {}
    for summary in summaries:
        session_id = summary.get("session_id", "")
        name = summary.get("session_name") or DEFAULT_SESSION_NAME
        if name_counts.get(name, 0) > 1:
            labels[session_id] = f"{name} · {session_id[:8]}"
        else:
            labels[session_id] = name
    return labels


def choose_initial_session(query_session: str | None, sessions: list[str]) -> str:
    if query_session and query_session in sessions:
        return query_session
    if sessions:
        return sessions[0]
    return resolve_session_id("")


def delete_session_artifacts(
    session_id: str,
    session_dir: Path = SESSION_DIR,
    trace_dir: Path = TRACE_DIR,
) -> list[Path]:
    store = SessionMemoryStore(session_dir)
    session_path = store._session_path(session_id)  # noqa: SLF001 - reuse memory validation rules
    paths = [
        session_path,
        session_path.with_name(f"{session_path.stem}.req_res.log"),
        trace_dir / f"{session_path.stem}.trace.log",
    ]

    deleted = []
    for path in paths:
        if path.exists():
            path.unlink()
            deleted.append(path)
    return deleted


def create_session(runtime: AgentRuntime, session_name: str | None = None) -> str:
    if not (isinstance(session_name, str) and session_name.strip()):
        existing_session_id = find_default_untitled_session(runtime.memory_store)
        if existing_session_id:
            return existing_session_id
    session = runtime.memory_store.create(session_name=session_name)
    return session["session_id"]


def find_default_untitled_session(memory_store: SessionMemoryStore) -> str | None:
    finder = getattr(memory_store, "find_default_untitled_session", None)
    if callable(finder):
        return finder()

    candidates: list[tuple[str, str]] = []
    root_dir = Path(getattr(memory_store, "root_dir", SESSION_DIR))
    if not root_dir.exists():
        return None

    for path in root_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue

        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        session_name = data.get("session_name") or metadata.get("session_name")
        source = metadata.get("session_name_source")
        if session_name == DEFAULT_SESSION_NAME and source in {"default", "generated"}:
            created_at = str(metadata.get("created_at", ""))
            candidates.append((created_at, path.stem))

    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0][1]


def delete_confirm_key(session_id: str) -> str:
    return f"confirm_delete::{session_id}"


def delete_button_key(session_id: str) -> str:
    return f"delete_session::{session_id}"


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
        runtime = _get_runtime()
        sessions = list_session_ids()
        query_session = _get_query_session(st)
        if query_session and query_session in sessions:
            session_id = query_session
        elif sessions:
            session_id = sessions[0]
        elif query_session:
            session_id = query_session
        else:
            session_id = create_session(runtime, "")
        st.session_state.session_id = session_id
        _set_query_session(st, st.session_state.session_id)


def _render_sidebar(st, runtime: AgentRuntime):
    st.sidebar.header("Session")
    current = st.session_state.session_id
    ensure_session_exists(runtime, current)
    session_summaries = list_session_summaries()
    sessions = [session["session_id"] for session in session_summaries]
    labels = build_session_labels(session_summaries)
    if sessions:
        selected = st.sidebar.selectbox(
            "切换会话",
            sessions,
            index=sessions.index(current) if current in sessions else len(sessions) - 1,
            format_func=lambda session_id: labels.get(session_id, session_id),
        )
        if selected != current:
            st.session_state.session_id = selected
            _set_query_session(st, selected)
            st.rerun()

    manual_session_name = st.sidebar.text_input(
        "新会话名称 / Session ID",
        value="",
        placeholder="输入 session 名称，可留空",
    )
    if st.sidebar.button("新建", use_container_width=True):
        session_id = create_session(runtime, manual_session_name)
        st.session_state.session_id = session_id
        _set_query_session(st, session_id)
        st.rerun()

    session_id = st.session_state.session_id
    with st.sidebar.expander("会话管理", expanded=False):
        st.caption("删除当前会话会同时删除 session、Req/Res 日志和工具 trace。")
        confirm_delete = st.checkbox("确认删除当前会话", key=delete_confirm_key(session_id))
        if st.button(
            "删除当前会话",
            disabled=not confirm_delete,
            key=delete_button_key(session_id),
            use_container_width=True,
        ):
            delete_session_artifacts(session_id)
            remaining_sessions = list_session_ids()
            next_session = remaining_sessions[0] if remaining_sessions else create_session(runtime, "")
            ensure_session_exists(runtime, next_session)
            st.session_state.session_id = next_session
            _set_query_session(st, next_session)
            st.rerun()

    st.sidebar.divider()
    task_panel = st.sidebar.empty()
    with task_panel.container():
        _render_task_panel(st, runtime.memory_store.get_todo_list(session_id))
    st.sidebar.divider()
    trace_records = TraceLogger(TRACE_DIR).read_records(session_id)
    st.sidebar.subheader("最近工具调用")
    if trace_records:
        last = trace_records[-1]
        st.sidebar.caption(f"{last.get('tool')} · step {last.get('step')}")
        st.sidebar.code(_compact_json(last.get("arguments", {})), language="json")
    else:
        st.sidebar.caption("暂无工具调用")
    return session_id, task_panel


def ensure_session_exists(runtime: AgentRuntime, session_id: str) -> None:
    session = runtime.memory_store.load(session_id)
    runtime.memory_store.save(session)


def _get_query_session(st) -> str | None:
    raw_session = st.query_params.get("session")
    if isinstance(raw_session, list):
        raw_session = raw_session[0] if raw_session else None
    if isinstance(raw_session, str) and raw_session.strip():
        return raw_session.strip()
    return None


def _set_query_session(st, session_id: str) -> None:
    st.query_params["session"] = session_id


def _render_task_panel(container, todo_list: list[dict[str, Any]]) -> None:
    container.markdown('<div class="task-panel-title">Task List</div>', unsafe_allow_html=True)
    if not todo_list:
        container.markdown('<div class="task-empty">暂无任务</div>', unsafe_allow_html=True)
        return

    counts = {
        "not-started": sum(1 for item in todo_list if item.get("status") == "not-started"),
        "in-progress": sum(1 for item in todo_list if item.get("status") == "in-progress"),
        "completed": sum(1 for item in todo_list if item.get("status") == "completed"),
    }
    total = len(todo_list)
    completed_pct = int((counts["completed"] / total) * 100) if total else 0
    container.markdown(
        f"""
        <div class="task-summary">
          <div class="task-summary-item done"><span>{counts["completed"]}</span><small>已完成</small></div>
          <div class="task-summary-item active"><span>{counts["in-progress"]}</span><small>进行中</small></div>
          <div class="task-summary-item todo"><span>{counts["not-started"]}</span><small>未开始</small></div>
        </div>
        <div class="task-progress"><div style="width:{completed_pct}%"></div></div>
        """,
        unsafe_allow_html=True,
    )

    status_label = {
        "not-started": "未开始",
        "in-progress": "进行中",
        "completed": "已完成",
    }
    status_class = {
        "not-started": "todo",
        "in-progress": "active",
        "completed": "done",
    }
    for item in todo_list:
        status = item.get("status", "not-started")
        css_status = status_class.get(status, "todo")
        container.markdown(
            f"""
            <div class="task-card {css_status}">
              <div class="task-card-top">
                <span class="task-id">#{item.get("id")}</span>
                <span class="task-badge {css_status}">{status_label.get(status, status)}</span>
              </div>
              <div class="task-title">{_escape_html(item.get("title", ""))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


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
                    with st.expander("tool_use", expanded=False):
                        for tool_call in message["tool_calls"]:
                            st.markdown(format_tool_call(tool_call))
                if message.get("content"):
                    st.markdown(message["content"])
        elif role == "tool":
            with st.chat_message("assistant", avatar=SYSTEM_AVATAR):
                with st.expander(f"tool_result · {message.get('name', 'unknown')}", expanded=False):
                    st.code(message.get("content", ""), language="json")


def _run_web_turn(st, runtime: AgentRuntime, session_id: str, user_input: str, live_area, task_placeholder) -> None:
    with live_area:
        with st.chat_message("user"):
            st.markdown(user_input)
        live_state: dict[str, Any] = {}

        def ensure_assistant_block() -> dict[str, Any]:
            if live_state.get("block") is None:
                chat = st.chat_message("assistant")
                with chat:
                    live_state["block"] = {
                        "reasoning_parts": [],
                        "answer_parts": [],
                        "tool_lines": [],
                        "reasoning_slot": st.empty(),
                        "tool_slot": st.empty(),
                        "answer_placeholder": st.empty(),
                        "reasoning_closed": False,
                        "tool_closed": False,
                    }
            return live_state["block"]

        def close_assistant_block() -> None:
            block = live_state.get("block")
            if block:
                collapse_reasoning(block)
                collapse_tool_use(block, delay=False)
            live_state["block"] = None

        def render_reasoning(block: dict[str, Any], expanded: bool) -> None:
            text = "".join(block["reasoning_parts"])
            if not text:
                return
            _render_live_expander(
                st=st,
                slot=block["reasoning_slot"],
                title="reasoning",
                body=text,
                expanded=expanded,
            )

        def collapse_reasoning(block: dict[str, Any]) -> None:
            if block.get("reasoning_closed"):
                return
            if block.get("reasoning_parts"):
                render_reasoning(block, expanded=False)
            block["reasoning_closed"] = True

        def render_tool_use(block: dict[str, Any], expanded: bool) -> None:
            if not block.get("tool_lines"):
                return
            _render_live_expander(
                st=st,
                slot=block["tool_slot"],
                title="tool_use",
                body="\n\n".join(block["tool_lines"]),
                expanded=expanded,
            )

        def collapse_tool_use(block: dict[str, Any], delay: bool = True) -> None:
            if block.get("tool_closed"):
                return
            if block.get("tool_lines"):
                if delay:
                    time.sleep(LIVE_AUTO_COLLAPSE_SECONDS)
                render_tool_use(block, expanded=False)
            block["tool_closed"] = True

        def render_tool_result(execution: dict[str, Any]) -> None:
            with st.chat_message("assistant", avatar=SYSTEM_AVATAR):
                slot = st.empty()
            _render_live_expander(
                st=st,
                slot=slot,
                title=f"tool_result · {execution.get('tool', 'unknown')}",
                body=_compact_json(execution.get("result")),
                expanded=True,
                language="json",
            )
            time.sleep(LIVE_AUTO_COLLAPSE_SECONDS)
            _render_live_expander(
                st=st,
                slot=slot,
                title=f"tool_result · {execution.get('tool', 'unknown')}",
                body=_compact_json(execution.get("result")),
                expanded=False,
                language="json",
            )

        def on_event(event: dict[str, Any]) -> None:
            event_type = event.get("type")
            if event_type == "reasoning_delta":
                block = ensure_assistant_block()
                block["reasoning_parts"].append(event.get("delta", ""))
                block["reasoning_closed"] = False
                render_reasoning(block, expanded=True)
            elif event_type == "content_delta":
                block = ensure_assistant_block()
                collapse_reasoning(block)
                block["answer_parts"].append(event.get("delta", ""))
                block["answer_placeholder"].markdown("".join(block["answer_parts"]))
            elif event_type == "tool_call":
                block = ensure_assistant_block()
                collapse_reasoning(block)
                block["tool_lines"].append(format_tool_call(event.get("tool_call", {})))
                block["tool_closed"] = False
                render_tool_use(block, expanded=True)
                collapse_tool_use(block)
            elif event_type == "tool_result":
                close_assistant_block()
                render_tool_result(event.get("execution", {}))
            elif event_type == "task_list":
                with task_placeholder.container():
                    _render_task_panel(st, runtime.memory_store.get_todo_list(session_id))
            elif event_type == "session_title":
                pass
            elif event_type == "message":
                close_assistant_block()

        runtime.run_turn(user_input=user_input, session_id=session_id, on_event=on_event)
        st.rerun()


def _render_live_expander(
    st,
    slot,
    title: str,
    body: str,
    expanded: bool,
    language: str | None = None,
) -> None:
    slot.empty()
    with slot.container():
        with st.expander(title, expanded=expanded):
            if language:
                st.code(body, language=language)
            else:
                st.markdown(body)


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


def _escape_html(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _inject_css(st) -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.5rem; max-width: 1180px; }
        section[data-testid="stSidebar"] { min-width: 310px; }
        div[data-testid="stChatMessage"] { border-radius: 6px; padding: 0.25rem 0; }
        code { white-space: pre-wrap !important; }
        .task-panel-title {
            font-weight: 800;
            font-size: 1rem;
            margin: 0.15rem 0 0.65rem;
        }
        .task-empty {
            border: 1px dashed #c8ced8;
            color: #6b7280;
            border-radius: 8px;
            padding: 0.75rem;
            text-align: center;
            background: #f8fafc;
        }
        .task-summary {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 0.4rem;
            margin-bottom: 0.55rem;
        }
        .task-summary-item {
            border-radius: 8px;
            padding: 0.55rem 0.35rem;
            text-align: center;
            border: 1px solid #e5e7eb;
            background: #ffffff;
        }
        .task-summary-item span {
            display: block;
            font-weight: 800;
            font-size: 1.05rem;
        }
        .task-summary-item small {
            display: block;
            font-size: 0.7rem;
            color: #5b6472;
            margin-top: 0.1rem;
        }
        .task-summary-item.done span { color: #15803d; }
        .task-summary-item.active span { color: #b45309; }
        .task-summary-item.todo span { color: #475569; }
        .task-progress {
            height: 7px;
            border-radius: 999px;
            overflow: hidden;
            background: #e5e7eb;
            margin: 0.15rem 0 0.7rem;
        }
        .task-progress div {
            height: 100%;
            background: linear-gradient(90deg, #16a34a, #22c55e);
            border-radius: 999px;
        }
        .task-card {
            border-radius: 8px;
            padding: 0.7rem 0.75rem;
            margin: 0.45rem 0;
            border: 1px solid #e5e7eb;
            background: #ffffff;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
        }
        .task-card.active {
            border-color: #f59e0b;
            background: #fffbeb;
            box-shadow: 0 0 0 1px rgba(245, 158, 11, 0.16);
        }
        .task-card.done {
            background: #f0fdf4;
            border-color: #bbf7d0;
            opacity: 0.82;
        }
        .task-card.todo {
            background: #f8fafc;
            border-color: #d8dee8;
        }
        .task-card-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 0.4rem;
            margin-bottom: 0.35rem;
        }
        .task-id {
            font-size: 0.72rem;
            font-weight: 700;
            color: #64748b;
        }
        .task-badge {
            border-radius: 999px;
            padding: 0.12rem 0.45rem;
            font-size: 0.68rem;
            font-weight: 800;
            white-space: nowrap;
        }
        .task-badge.active {
            color: #92400e;
            background: #fef3c7;
            border: 1px solid #fde68a;
        }
        .task-badge.done {
            color: #166534;
            background: #dcfce7;
            border: 1px solid #bbf7d0;
        }
        .task-badge.todo {
            color: #334155;
            background: #e2e8f0;
            border: 1px solid #cbd5e1;
        }
        .task-title {
            font-size: 0.88rem;
            font-weight: 700;
            line-height: 1.35;
            color: #111827;
            word-break: break-word;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
