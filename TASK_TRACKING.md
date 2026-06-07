# 任务追踪

用于跨 session 协作时快速恢复项目状态。

## 当前阶段

- 当前步骤：步骤 14/17 - Prompt 与问题解决记录
- 状态：进行中
- 更新时间：2026-06-07

## 已完成

- 创建基础项目目录结构。
- 创建 `.env.example`。
- 创建 `requirements.txt`。
- 创建 README 初稿。
- 创建 Prompt 与问题解决记录文档。
- 创建结构校验测试。
- 已在 `mcp-learn` 环境运行结构测试。
- 实现 `.env` 配置读取：`src/agent/config.py`。
- 实现 OpenAI SDK 版 DeepSeek LLM client：`src/agent/llm.py`。
- 实现 assistant message 解析结构：`src/agent/schemas.py`。
- LLM 封装支持解析 `reasoning_content`、正式回答 `content` 和原生 `tool_calls`。
- LLM 封装支持真正的流式事件解析：
  - `reasoning_content` delta 到达后立即产出 `reasoning_delta` 事件。
  - `content` delta 到达后立即产出 `content_delta` 事件。
  - `tool_calls` delta 到达后先累积并产出 `tool_call_delta` 事件。
  - 完整工具调用形成后产出 `tool_call` 事件，供 runtime 触发工具执行。
  - 最后产出完整 assistant `message` 事件，供本地 session 持久化。
- 新增真实 DeepSeek API 测试：`tests/test_llm_client.py`。
- 新增配置读取测试：`tests/test_config.py`。
- 实现 tool registry：`src/tools/registry.py`，支持注册工具、导出 OpenAI-compatible `tools` schema、解析并执行 `tool_calls`。
- 实现 `calculator`：`src/tools/calculator.py`，使用 AST allowlist 安全计算简单数学表达式。
- 实现 `search`：`src/tools/search.py`，使用 Tavily Search API 返回标题、URL 和摘要。
- 实现 `manage_todo_list`：`src/tools/todo.py`，使用完整 `todoList` 同步方式管理 session 任务状态。
  - 工具参数要求一次传入完整任务列表。
  - 状态统一为 `not-started`、`in-progress`、`completed`。
  - 限制最多一个任务处于 `in-progress`。
  - runtime 执行工具后把列表持久化到当前 session 的 `memory.tasks`。
- 新增工具单元测试：`tests/test_tools.py`。
- 新增真实 LLM 工具调用与执行测试：`tests/test_llm_tool_execution.py`，覆盖 `calculator`、`search`、`todo`。
- 已在 `TASK_BREAKDOWN.md` 补充 message / assistant 响应细化设计：
  - 本地存储保留 assistant `reasoning_content`，用于展示和调试。
  - assistant 正式回答仍以 `content` 作为用户主回复。
  - 发送 LLM 请求时不把 `reasoning_content` 放入上下文。
  - session 本地 `messages` 需要经过上下文组装函数转换后再发送，不能原样复用。
  - 请求上下文目标规则：保留 `role=tool` 工具消息、模型正式回答消息，以及 assistant `tool_calls` 响应消息。
  - assistant `tool_calls` 响应消息必须保留，用于和后续 `role=tool` 的 `tool_call_id` 对齐，但不能携带 `reasoning_content`。
- 实现 session memory：`src/agent/memory.py`。
  - 支持按 session JSON 读写。
  - 支持中文 session 名称；仍禁止路径穿越、路径分隔符和 Windows 非法文件名字符。
  - 支持本地保存 user / assistant / tool 消息流水。
  - assistant 消息本地保留 `content`、`reasoning_content` 和 `tool_calls`。
  - 实现 `build_llm_context()`，从本地完整 `messages` 生成 LLM 请求上下文。
  - 上下文组装时过滤 `reasoning_content` 和本地 `metadata`。
  - 上下文组装时保留 `role=tool` 工具消息、assistant 正式回答消息和 assistant `tool_calls` 响应消息。
  - 支持保存 `memory.tasks` 并注入 session 任务状态摘要。
- 新增 session memory 测试：`tests/test_memory.py`。
- 实现 AgentRuntime 基础循环：`src/agent/runtime.py`。
  - 支持多轮 session 对话。
  - 调 LLM 前使用 `build_llm_context()` 组装请求上下文，不直接复用本地完整消息。
  - 使用 `DeepSeekClient.stream_chat_events()` 消费真正的流式事件。
  - 支持实时接收 `reasoning_delta`、`content_delta`、`tool_call` 和 `message` 事件。
  - assistant 完整响应保存到 session，用户主回复只使用 `content`。
  - 检测 `tool_calls` 后执行本地工具，将工具结果追加为 `role=tool` 消息，再继续下一轮 LLM。
  - 默认开启 thinking mode，且不显式设置 `tool_choice`。
  - 执行 `manage_todo_list` 后同步 session 级 `memory.tasks`，并发出 `task_list` 事件供 CLI 展示。
  - 完成 `MAX_AGENT_STEPS` 收束策略：达到最大步数且已有工具结果时，追加内部收束提示并进行一次不传 `tools` 的最终 LLM 调用。
  - 每次 LLM stream step 记录 session 级 `req_res.log`：`data/sessions/{session_id}.req_res.log`。
  - `req_res.log` 记录脱敏 request 和处理后的完整 response；流式 chunks 保留在 response 的 `_stream_chunks` 字段。
  - 请求 system prompt 默认注入上海时区 runtime context：
    - `Current date`
    - `Current time`
    - `Timezone: Asia/Shanghai`
    - `Locale: zh-CN`
- 实现 CLI 基础交互：`src/main.py`。
  - 支持 `--session`。
  - `--session` 可留空；留空时自动生成 `YYYYMMDD-HHMMSS-uuid` session id。
  - 支持交互式多轮输入。
  - 支持 `--once` 单轮命令，方便录屏和 smoke test。
  - 默认开启 debug 展示，可用 `--no-debug` 关闭。
  - reasoning 流式输出使用 `[reasoning]...[/reasoning]` 包裹，避免每个 token 重复打印标签。
  - 启动已有 session 时打印最近 5 条本地上下文消息，按 `user_prompt`、`reasoning`、`tool_call`、`tool_result` 等格式展示。
  - 启动 session 时读取并展示当前 `todo_list`。
  - 每次模型调用 `manage_todo_list` 并完成工具执行后，CLI 立即展示最新 `todo_list`。
- 新增 AgentRuntime 单元测试：`tests/test_runtime.py`。
- 新增 CLI 展示测试：`tests/test_cli.py`。
- 实现工具调用 trace logger：`src/agent/trace.py`。
  - 每个 session 汇总写入 `data/traces/{session_id}.trace.log`。
  - 每条 trace 记录 `session_id`、`turn_id`、`step`、`tool_call_id`、`tool`、`arguments`、`result`、`error`、`raw_tool_call`、`timestamp`。
  - AgentRuntime 每次工具执行后立即追加 trace。
- 新增 trace 测试：`tests/test_trace.py`。
- 实现 Streamlit Web 页面：`src/web.py`。
  - 左侧统一 session 管理：选择已有 session、输入 session、新建 session。
  - 打开会话后展示当前 session 的全部对话记录。
  - assistant 消息支持展开查看 `reasoning_content`。
  - assistant `tool_calls` 以 `tool_use` 区域展示。
  - `role=tool` 工具结果以 `tool_result` 区域展示。
  - 侧边栏常驻展示当前 session 的 `todo_list`。
  - runtime 发出 `task_list` 事件时，Web 实时刷新任务列表。
  - Web 输入仍调用同一套 `AgentRuntime.run_turn()`，不单独实现 agent loop。
  - 提供 `工具 Trace` 和 `Req/Res` 标签页查看汇总日志。
- 新增 Web helper 测试：`tests/test_web.py`。
- 强化 `manage_todo_list` 调用协议：
  - 工具 schema 明确要求创建任务列表时调用 `manage_todo_list`。
  - 任务开始前必须提交完整 `todoList`，把当前任务标记为 `in-progress`。
  - 任务完成后、给出最终答复前必须再次提交完整 `todoList`，把当前任务标记为 `completed`。
  - 默认 system prompt 和 session task memory 摘要都加入状态变更写回规则，避免模型只在文字里说明任务完成。
- 强化 `search` 使用策略：
  - 用户明确要求搜索、查询、联网确认时使用。
  - 问题依赖当前日期、最新进展、价格、天气、新闻、版本、政策等实时性信息时使用。
  - 模型自身知识储备不足以可靠回答时使用。
  - 稳定常识、简单计算、纯聊天或已有上下文可可靠回答时不调用 `search`。
- 优化 Web 实时对话气泡行为：
  - live `reasoning` 使用独立 placeholder 渲染，推理流结束后立即替换为折叠态。
  - live `tool_use` 显示约 2 秒后自动替换为折叠态。
  - live `tool_result` 仍保持原有对话块展示形式和系统图标，显示约 2 秒后自动折叠。
  - 不再等整轮 agent loop 完成后才统一折叠所有 live 气泡。
- 完善 Web session 管理：
  - 当前 session 同步到 URL query param，刷新页面后保持原 session。
  - session 列表按 session `metadata.created_at` 时间顺序展示；缺少 metadata 的旧文件退回文件修改时间排序。
  - 首次进入且 URL 未指定 session 时，默认打开按时间排序后的第一个 session。
  - 侧边栏增加删除当前会话功能，同时删除 session JSON、Req/Res 日志和工具 trace。
  - 删除当前会话后自动跳转到按时间排序后的第一个 session；如果没有剩余 session，则自动创建新 session。
  - 删除确认 checkbox 和删除按钮使用 session 级 key，切换会话后不会复用上一个 session 的确认状态。
- 修正 Web task list 实时更新：
  - runtime 执行 `manage_todo_list` 后先写入 session `memory.tasks`，立即发出 `task_list` 事件，再发出 `tool_result`。
  - Web 侧复用同一个 sidebar task panel placeholder，不再额外追加临时 task list。
  - 收到 `task_list` 事件后从当前 session 持久化文件重新读取 todo list 并渲染，不依赖整轮 agent loop 完成后的 rerun。
- 调整 LLM 输出上限：
  - AgentRuntime 默认 `max_tokens` 从 `1000` 调整为 `65536`。
  - session `req_res.log` 中记录的 request 和实际 `stream_chat_events()` 调用保持一致。
  - 真实工具调用测试 helper 的请求记录也同步为 `65536`，避免日志样例仍显示旧值。
- Streamlit Web 页面已完成并经过多轮迭代完善：
  - 完成与 CLI 共用的 session 管理、对话历史、reasoning、tool_use、tool_result、trace、req/res 展示。
  - 支持工具调用、多轮对话、中文 session、刷新保持当前 session、按时间顺序展示 session。
  - 支持新建和删除当前 session，删除时同步清理 session JSON、req/res log 和 trace log。
  - task list 侧边栏 UI 已增强，并支持 `manage_todo_list` 调用后的实时持久化读取与重绘。
  - live 对话气泡行为已优化：reasoning/tool_use/tool_result 可在流式过程中按阶段自动折叠。
  - Req/Res 默认不渲染大 JSON，按需加载原始日志，优先保证页面流畅。
- 已补充 README：
  - 介绍项目内容、功能清单、技术实现和运行方式。
  - 说明自建 Agent loop、最大步数限制、工具列表、trace 与 req/res 日志。
  - 说明 memory 的召回时机与放置方式。
  - 单独增加录屏展示章节，并按裸链接形式放置视频链接。

## 验证记录

```bash
conda run -n mcp-learn pytest -q
```

结果：

```text
2 passed
```

最近一次验证：

```bash
conda run -n mcp-learn pytest -q
```

结果：

```text
19 passed
```

LLM 流式解析专项验证：

```bash
conda run -n mcp-learn pytest -q tests\test_llm_client.py
```

结果：

```text
7 passed
```

工具设计与真实 LLM 工具调用专项验证：

```bash
conda run -n mcp-learn pytest -q tests\test_tools.py
conda run -n mcp-learn pytest -q tests\test_llm_tool_execution.py
```

结果：

```text
6 passed
3 passed
```

Session memory 专项验证：

```bash
conda run -n mcp-learn pytest -q tests\test_memory.py
```

结果：

```text
7 passed
```

本地非联网测试验证：

```bash
conda run -n mcp-learn pytest -q tests\test_config.py tests\test_project_structure.py tests\test_tools.py tests\test_memory.py
```

结果：

```text
18 passed
```

本次尝试运行全量测试时，真实 DeepSeek API 相关测试因当前环境 SSL 证书校验失败中断：

```text
CERTIFICATE_VERIFY_FAILED
7 failed, 19 passed
```

失败集中在联网真实 API 测试，不是本次 `memory.py` 改动导致的本地测试回归。

切换网络环境后重跑失败的联网测试：

```bash
conda run -n mcp-learn pytest -q tests\test_llm_client.py
conda run -n mcp-learn pytest -q tests\test_llm_tool_execution.py
```

结果：

```text
5 passed
3 passed
```

随后重跑全量测试：

```bash
conda run -n mcp-learn pytest -q
```

结果：

```text
26 passed
```

修正流式解析为逐 chunk 事件流后重跑：

```bash
conda run -n mcp-learn pytest -q tests\test_llm_client.py
conda run -n mcp-learn pytest -q
```

结果：

```text
7 passed
28 passed
```

AgentRuntime 专项验证：

```bash
conda run -n mcp-learn pytest -q tests\test_runtime.py
```

结果：

```text
3 passed
```

实现 AgentRuntime / CLI 后重跑全量测试：

```bash
conda run -n mcp-learn pytest -q
```

结果：

```text
31 passed
```

CLI 展示优化后验证：

```bash
conda run -n mcp-learn pytest -q tests\test_cli.py tests\test_runtime.py
conda run -n mcp-learn pytest -q
```

结果：

```text
5 passed
33 passed
```

Session 级 req/res 日志、runtime context、空 session 自动生成验证：

```bash
conda run -n mcp-learn pytest -q tests\test_runtime.py tests\test_cli.py
conda run -n mcp-learn pytest -q
conda run -n mcp-learn python -m src.main --once "你好，简单回复 OK" --no-debug
```

结果：

```text
7 passed
35 passed
Created session: 20260607-122216-38b02f21
Agent> OK
```

`manage_todo_list` 改造和 session 级任务记忆验证：

```bash
conda run -n mcp-learn pytest -q tests\test_tools.py tests\test_memory.py tests\test_runtime.py tests\test_cli.py
conda run -n mcp-learn pytest -q tests\test_llm_tool_execution.py
conda run -n mcp-learn pytest -q
```

结果：

```text
23 passed
3 passed
38 passed
```

Trace logger 验证：

```bash
conda run -n mcp-learn pytest -q tests\test_trace.py tests\test_runtime.py
conda run -n mcp-learn pytest -q
conda run -n mcp-learn python -m src.main --session trace-smoke --once "帮我算一下 (12 + 8) * 3" --no-debug
```

结果：

```text
9 passed
41 passed
Agent> (12 + 8) * 3 = **60** ✅
```

真实 trace 文件：

```text
data/traces/trace-smoke.trace.log
```

Web 页面验证：

```bash
conda run -n mcp-learn pytest -q tests\test_web.py tests\test_project_structure.py
conda run -n mcp-learn pytest -q
conda run -n mcp-learn streamlit run src/web.py --server.port 8501 --server.headless true
```

结果：

```text
6 passed
46 passed
Streamlit listening on http://localhost:8501
```

中文 session 名称验证：

```bash
conda run -n mcp-learn pytest -q tests\test_memory.py tests\test_web.py
conda run -n mcp-learn pytest -q
```

结果：

```text
14 passed
49 passed
```

Todo 状态更新协议强化验证：

```bash
conda run -n mcp-learn pytest -q tests\test_tools.py tests\test_memory.py tests\test_runtime.py
conda run -n mcp-learn pytest -q
conda run -n mcp-learn python -m src.main --session todo-status-smoke --once "创建一个任务列表，先搜索什么是RAG，再搜索有哪些RAG框架，最后搜索最新RAG前沿技术，只完成第一个任务即可" --no-debug
```

结果：

```text
25 passed
51 passed
真实 smoke trace 顺序：manage_todo_list(create) -> manage_todo_list(in-progress) + search -> manage_todo_list(completed)
session memory 最终状态：任务 1 completed，任务 2/3 not-started
```

Web live 气泡折叠行为验证：

```bash
conda run -n mcp-learn pytest -q tests\test_web.py
conda run -n mcp-learn pytest -q
```

结果：

```text
5 passed
51 passed
```

Web session 保持与删除功能验证：

```bash
conda run -n mcp-learn pytest -q tests\test_web.py
```

结果：

```text
8 passed
```

Search 使用策略验证：

```bash
conda run -n mcp-learn pytest -q tests\test_tools.py tests\test_runtime.py
```

结果：

```text
18 passed
```

Web task list 实时更新验证：

```bash
conda run -n mcp-learn pytest -q tests\test_runtime.py tests\test_web.py
```

结果：

```text
17 passed
```

Runtime max_tokens 调整验证：

```bash
conda run -n mcp-learn pytest -q tests\test_runtime.py
```

结果：

```text
9 passed
```

最大步数收束策略验证：

```bash
conda run -n mcp-learn pytest -q tests\test_runtime.py
conda run -n mcp-learn pytest -q
```

结果：

```text
7 passed
42 passed
```

CLI smoke test：

```bash
conda run -n mcp-learn python -m src.main --session cli-smoke --once "帮我算一下 (12 + 8) * 3"
```

结果摘要：

```text
Agent> 没问题，马上计算。计算结果：**(12 + 8) × 3 = 60**。
```

README 文档更新：

```text
仅文档改动，未运行测试。
```

## 未完成

- 步骤 14：补充 Prompt 与问题解决记录。
- 步骤 15：整理 CLI 示例命令与录屏用例。
- 步骤 16：整理 Web 示例流程与录屏用例。
- 步骤 17：准备录屏。

## 设计决策记录

- 每完成一个功能步骤，需要同步生成或更新合适的测试文件。
- 步骤完成后优先只运行当前步骤相关测试文件，不默认运行全量 `pytest`。
- 全量测试只在阶段性收尾、共享模块变更、影响多个功能边界或用户明确要求时运行。
- 每次验证需要在本文件记录测试命令和结果，方便跨 session 接续。
- 使用 DeepSeek API 原生工具调用协议，即 OpenAI-compatible `tools/tool_calls`。
- 不要求模型输出自定义 JSON；runtime 读取 assistant message 中的 `tool_calls`，执行本地工具，再追加 `role=tool` 消息。
- LLM client 使用 `openai` SDK，不手写底层 HTTP 请求。
- 默认保留 DeepSeek thinking mode，并解析 `reasoning_content` 和正式回答 `content`。
- runtime 后续应优先消费 `DeepSeekClient.stream_chat_events()`，而不是等待 `chat_stream_parsed()` 返回完整结果；`chat_stream_parsed()` 仅作为兼容 helper。
- AgentRuntime 已使用 `stream_chat_events()`，CLI 可实时打印正式回答 delta；`--debug` 可展示 reasoning 和工具事件。
- 每个 session 对应一个 req/res 日志文件：`data/sessions/{session_id}.req_res.log`，用于复盘真实请求和处理后响应；流式 chunks 保留在 response 的 `_stream_chunks` 字段。
- runtime prompt 默认注入上海时区上下文，locale 固定为 `zh-CN`。
- CLI session 可留空，留空时自动生成 `YYYYMMDD-HHMMSS-uuid` 格式 session id。
- CLI/Web session 名称支持中文；底层直接保存为中文 JSON 文件名，同时继续拒绝 `..`、路径分隔符和 Windows 非法文件名字符。
- `reasoning_content` 只用于本地保存、调试和展示，不作为下一次 LLM 请求上下文发送。
- 本地 session `messages` 是完整记录，不等同于 LLM 请求 payload；发送前必须通过上下文组装函数过滤和转换。
- 请求上下文保留 `role=tool` 工具结果消息、assistant 正式回答消息和 assistant `tool_calls` 响应消息；assistant `tool_calls` 消息只包含协议所需字段，不携带 `reasoning_content`。
- DeepSeek thinking mode 不支持显式 `tool_choice`；真实工具调用测试通过“只传入目标工具 schema”约束模型调用对应工具。
- 核心 runtime 仍然自建，包括工具注册、工具执行、循环控制、session memory 和 trace。
- 对话历史和 session memory 分开建模：`messages` 保存聊天流水，`memory.tasks` 保存跨轮次任务状态；两者可以在同一个 session JSON 文件中分字段保存。
- `memory.tasks` 在每轮调 LLM 前以摘要形式注入上下文；`manage_todo_list` 工具改变任务状态后立即整体写回当前 session。
- todo 工具不再暴露 `create/list/update` CRUD 操作，改为 `manage_todo_list(todoList=[...])` 完整列表同步；CLI/UI 读取 session memory 展示任务列表，不要求模型调用 list。
- trace 单独保存在 `data/traces/`，不混入结构化 memory。
- trace 是工具调用汇总日志，保留工具调用请求和工具执行结果；session 对话记录仍保存在 `data/sessions/{session_id}.json`。
- `search` 工具使用 Tavily Search API，不使用 mock；`TAVILY_API_KEY` 从 `.env` 读取。
- `MAX_AGENT_STEPS` 表示单轮用户输入里的最大 agent 决策步骤数。
- 达到最大步数时，不直接中断；如果已有工具结果，会追加一条内部用户提示，要求模型基于当前已有信息给出最终答案。
- 收束调用不再传入 `tools`，避免模型继续发起工具调用；如果没有可用文本答案，则返回兜底答案并记录 trace。
- Streamlit Web 页面当前按“可用产品界面”维护：优先保证会话切换、实时流式展示、task list 更新、日志查看和删除等核心交互稳定；后续只做必要微调，不再作为未完成模块追踪。

## 下一步建议

进入文档和录屏收尾：

- 更新 `PROMPTS_AND_NOTES.md`，整理 DeepSeek thinking、tool_choice、stream、todo、search、Web 交互等关键约束。
- 准备 CLI/Web 录屏脚本：普通对话、search、calculator、manage_todo_list、task list 持久化、session 删除与恢复。
- 非必要不跑全量测试；文档类改动通常不跑测试。
