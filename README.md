# Minimal Agent

从零实现的最小可用工具 Agent。项目使用真实 DeepSeek LLM API，采用 OpenAI-compatible `tools/tool_calls` 协议，但核心 runtime、工具注册、工具执行、session memory、trace 日志和最大步数控制均由本项目自行实现，没有直接依赖 LangChain、OpenHands 等现成 Agent 主流程框架。

项目同时提供 CLI 和 Streamlit Web 两个入口。两者共用同一个 `AgentRuntime`，Web 只负责交互展示，不重新实现 Agent loop。

> **快速导航**
>
> **重点阅读：** [AI Prompt 与问题解决记录](#ai-prompt-与问题解决记录)  
> **效果展示：** [录屏展示](#录屏展示)

## 功能概览

- 多轮对话：同一个 session 内保留历史消息，后续提问可以基于已有上下文理解指代。
- Session 维护：每个 session 独立保存到 `data/sessions/{session_id}.json`，支持中文 session 名称。
- 真实 LLM API：通过 OpenAI SDK 调用 DeepSeek API，默认开启 thinking mode，并解析 `reasoning_content`、正式回答 `content` 和原生 `tool_calls`。
- 自建 Agent loop：接收用户输入，调用 LLM 判断是否需要工具，执行工具，把 `role=tool` 结果写回上下文，继续循环直到最终回答。
- 工具调用：内置 `calculator`、`search`、`manage_todo_list` 三个工具。
- 跨轮次继续执行：`manage_todo_list` 会把任务列表写入 session memory，下一轮追问进度或继续任务时可以读取已有状态。
- 最大步数限制：单轮最多执行 `MAX_AGENT_STEPS` 次 Agent 决策；达到上限后进入无工具收束回答。
- 基本异常处理：配置缺失、LLM 请求异常、工具参数错误、工具运行异常、session 文件 JSON 错误等都有明确错误路径。
- Trace 与 Req/Res 日志：工具执行日志保存到 `data/traces/`，LLM 请求与响应摘要保存到 `data/sessions/*.req_res.log`。
- Web 展示：支持多 session 切换、刷新后恢复对话、实时流式输出、reasoning 折叠展示、tool_use/tool_result 展示、任务列表实时更新、日志查看和删除 session。

## 技术实现

- 语言：Python
- LLM：DeepSeek API，OpenAI-compatible Chat Completions
- LLM SDK：`openai`
- Web UI：`streamlit`
- 搜索工具：Tavily Search API
- 配置：`python-dotenv`
- 测试：`pytest`

主要目录：

```text
src/
  main.py              # CLI 入口
  web.py               # Streamlit Web 入口
  agent/
    runtime.py         # 自建 Agent loop
    llm.py             # DeepSeek/OpenAI-compatible API 封装
    memory.py          # session 持久化与 LLM 上下文组装
    trace.py           # 工具调用 trace
    config.py          # .env 配置读取
    schemas.py         # assistant message 解析结构
  tools/
    calculator.py      # 安全计算器
    search.py          # Tavily 搜索
    todo.py            # session 级任务列表管理
    registry.py        # 工具 schema 注册与执行
data/
  sessions/            # session JSON 与 req/res 日志
  traces/              # 工具调用 trace
tests/                 # 单元测试与集成测试
```

## 运行方式

建议使用项目开发时的 conda 环境：

```bash
conda activate mcp-learn
pip install -r requirements.txt
```

复制配置文件并填写 key：

```bash
copy .env.example .env
```

`.env` 示例：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
MAX_AGENT_STEPS=5
TAVILY_API_KEY=your_tavily_api_key_here
REQUEST_TIMEOUT=60
```

CLI 运行：

```bash
python -m src.main --session demo
```

单轮 CLI smoke test：

```bash
python -m src.main --session cli-smoke --once "帮我算一下 (12 + 8) * 3"
```

Web 运行：

```bash
streamlit run src/web.py
```

启动后浏览器访问 Streamlit 输出的本地地址，通常是：

```text
http://localhost:8501
```

## Agent Loop 设计

核心流程位于 `src/agent/runtime.py` 的 `AgentRuntime.run_turn()`：

1. 读取或创建当前 session。
2. 将用户输入追加到本地 `messages`。
3. 从 session memory 生成任务摘要，并通过 `build_llm_context()` 组装 LLM 请求上下文。
4. 从 `ToolRegistry` 导出 OpenAI-compatible `tools` schema。
5. 流式调用 DeepSeek API，实时接收 `reasoning_delta`、`content_delta`、`tool_call_delta`、`tool_call` 和最终 `message`。
6. 如果 assistant message 没有 `tool_calls`，保存回答并结束本轮。
7. 如果存在 `tool_calls`，runtime 本地执行对应工具。
8. 工具结果写入 `data/traces/{session_id}.trace.log`，同时以 `role=tool` 消息追加到 session。
9. 如果是 `manage_todo_list`，将完整任务列表同步到 `memory.tasks`，Web/CLI 立即刷新 task list。
10. 回到第 3 步继续循环，直到得到最终回答或达到最大步数。

达到 `MAX_AGENT_STEPS` 且已经有工具结果时，runtime 会追加内部收束提示，并进行一次不传 `tools` 的最终 LLM 调用，要求模型基于已有工具结果回答，避免无限工具循环。

## Memory 召回时机与放置方式

项目把聊天流水和结构化 memory 分开建模，物理上保存在同一个 session JSON 文件中：

```json
{
  "session_id": "demo",
  "messages": [],
  "memory": {
    "tasks": {},
    "facts": {},
    "preferences": {}
  },
  "metadata": {
    "created_at": "...",
    "updated_at": "..."
  }
}
```

放置方式：

- `messages`：保存完整本地聊天流水，包括 user、assistant、assistant tool_calls、tool result。
- `memory.tasks`：保存跨轮次任务状态，来自 `manage_todo_list` 的完整 task list。
- `memory.facts`、`memory.preferences`：预留字段，当前主要演示任务状态 memory。
- `data/traces/`：保存工具调用 trace，不混入聊天历史。
- `data/sessions/*.req_res.log`：保存每次 LLM 请求和响应摘要，便于复盘。

召回时机：

- 每轮用户输入开始时加载当前 session 文件。
- 调 LLM 前，`build_llm_context()` 会把最近对话历史转换为模型可接收的 messages。
- 调 LLM 前，`memory.tasks` 会被整理成任务状态摘要，注入 system prompt，而不是伪装成用户消息。
- 工具执行后，如果 `manage_todo_list` 改变任务状态，runtime 立即写回 `memory.tasks`。
- 最终回答后，assistant 正式回答保存回 `messages`。

需要注意：本地 `messages` 不会原样发给模型。`reasoning_content`、本地 `metadata` 等只用于展示和调试，不会进入下一次 LLM 请求上下文；assistant 的正式回答、assistant `tool_calls` 和 `role=tool` 工具结果会按协议保留。

## 工具列表

`calculator`

- 用途：计算简单数学表达式。
- 实现：使用 AST allowlist，只允许数字、运算符、括号和空格，避免直接 `eval`。
- 示例：`帮我算一下 889 * (554 - 3)`。

`search`

- 用途：联网搜索实时或不确定信息。
- 实现：调用 Tavily Search API，返回 query、answer、标题、URL 和摘要。
- 示例：`北京最近天气怎么样`。

`manage_todo_list`

- 用途：创建和更新 session 级任务列表。
- 实现：模型每次提交完整 `todoList`，runtime 校验后写入当前 session 的 `memory.tasks`。
- 状态：`not-started`、`in-progress`、`completed`，同一时间最多一个任务为 `in-progress`。
- 示例：第一轮创建 RAG 调研任务列表，第二轮输入 `现在完成第二个任务`，Agent 会基于已有 session 状态继续执行。

## 日志与可观察性

Session 文件：

```text
data/sessions/{session_id}.json
```

LLM 请求响应日志：

```text
data/sessions/{session_id}.req_res.log
```

工具 trace：

```text
data/traces/{session_id}.trace.log
```

Trace 记录字段包括：

- `session_id`
- `turn_id`
- `step`
- `tool_call_id`
- `tool`
- `arguments`
- `result`
- `error`
- `raw_tool_call`
- `timestamp`

Web 页面中也提供 `工具 Trace` 和 `Req/Res` 两个标签页，用于查看当前 session 的执行细节。

## AI Prompt 与问题解决记录

详细记录见 [PROMPTS_AND_NOTES.md](PROMPTS_AND_NOTES.md)。

本项目的 AI 协作不是一次性生成完整代码，而是按“任务拆解、模块实现、单元测试、进度追踪、持续纠偏”的方式完成。开发前先用 [TASK_BREAKDOWN.md](TASK_BREAKDOWN.md) 明确题目边界和实现顺序，包括自建 Agent runtime、DeepSeek 原生 `tool_calls`、session memory、最大步数收束策略和录屏验收用例。开发中用 [TASK_TRACKING.md](TASK_TRACKING.md) 记录每个模块的完成状态、测试命令、测试结果和设计决策，保证跨 session 后仍能恢复上下文继续协作。

实现过程中，我持续根据 Agent 运行原理修正 AI 的实现方向，例如：

- 明确不能使用现成 Agent loop，核心 `AgentRuntime` 必须自己实现。
- 要求使用 DeepSeek 原生 `tool_calls`，不让模型输出自定义 JSON 格式。
- 要求默认保留 thinking mode，并区分 `reasoning_content` 和正式 `content`。
- 将流式解析从“收集全部 chunks 后合并”修正为“逐 chunk 产出 delta 事件”。
- 区分对话历史和 session memory：`messages` 保存聊天流水，`memory.tasks` 保存跨轮次任务状态。
- 将 todo 工具改成 session 级 `manage_todo_list` 完整列表同步，而不是独立文件 CRUD。
- 每完成一个功能模块都补充对应测试，并优先运行相关测试文件。

原始 AI 对话记录保存在本地 `codex_sessions/` 目录中；提交文档中用 [PROMPTS_AND_NOTES.md](PROMPTS_AND_NOTES.md) 做了结构化整理，重点记录 prompt、问题、修正思路和最终落地结果。

## 录屏展示

### 1. 多轮对话、思考过程展示、流式输出

视频中先问“你知道中国吗”，再问“它的经济中心在哪里”。页面正常展示 reasoning 和正式回答，并能识别“它”指代中国，说明支持多轮对话。

https://github.com/user-attachments/assets/49875343-2a8f-49e9-813c-dc7fe73b005a

### 2. 同一个 session 对话记录持久化

刷新页面后，对话记录仍然加载出来；在之前对话基础上继续询问“它有多少个民族”，Agent 仍能基于上下文回答。示例数据可查看 [data/sessions/简单测试.json](data/sessions/简单测试.json)，请求响应详情可查看 [data/sessions/简单测试.req_res.log](data/sessions/简单测试.req_res.log)。

https://github.com/user-attachments/assets/80d4e15b-b809-433c-8564-16a803ed8100

### 3. 多 session 管理，各 session 独立

视频中切换不同 session，每个 session 都有自己的对话记录和渲染状态。

https://github.com/user-attachments/assets/28f73a59-a8a3-4476-970a-b347e1adf96d

### 4. 工具调用示例：search

询问“北京最近天气怎么样”，模型生成 `search` 的 `tool_use`，系统自动执行工具并展示 `tool_result`。

https://github.com/user-attachments/assets/c9a45478-f1fd-4235-b8b8-a57b54afc944

### 5. 工具调用示例：calculator

询问“计算一下 889*(554-3)”，模型生成工具调用，系统执行计算并展示工具调用信息。示例数据可查看 [data/sessions/简单工具调用.json](data/sessions/简单工具调用.json)，请求响应详情可查看 [data/sessions/简单工具调用.req_res.log](data/sessions/简单工具调用.req_res.log)。

https://github.com/user-attachments/assets/dd4ab8db-a268-417c-a0d8-1d423eef1904

### 6. Task List 与跨轮次继续执行

先输入“创建一个任务列表，先搜索什么是RAG，再搜索有哪些RAG框架，最后搜索最新RAG前沿技术，只完成第一个任务即可”。模型调用 `manage_todo_list` 创建任务列表，并在任务状态变化时继续调用该工具写回完整 task list。刷新后 task 状态仍然保留。

随后输入“现在完成第二个任务”，Agent 会读取当前 session 的任务状态，继续执行第二个任务，并实时更新左侧任务列表。示例数据可查看 [data/sessions/持久化任务.json](data/sessions/持久化任务.json)，请求响应详情可查看 [data/sessions/持久化任务.req_res.log](data/sessions/持久化任务.req_res.log)。

https://github.com/user-attachments/assets/dc918742-fd45-42e6-8a1f-1cfb810f95d4

### 7. 工具调用日志详情

Web 页面可以查看每个 session 的工具调用日志，包括工具名称、参数和执行结果。

https://github.com/user-attachments/assets/7c791baf-1398-493e-be13-70c73939c444

## 测试

运行测试：

```bash
pytest -q
```

项目测试覆盖配置读取、LLM 流式解析、工具注册与执行、session memory、runtime loop、trace、CLI 和 Web helper。最近记录的全量测试结果可在 `TASK_TRACKING.md` 中查看。
