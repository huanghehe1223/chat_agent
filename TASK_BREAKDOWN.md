# 最小可用 Agent 任务拆解

## 1. 题意边界确认

题目里的“框架完成主流程（如 LangChain / OpenHands 等），核心 runtime 需要自己实现”可以理解为：

- 可以使用普通依赖库辅助开发，例如 `requests`、`python-dotenv`、`pydantic`、`rich` 等。
- 可以参考 LangChain / OpenHands / Claude Agent SDK 的设计思想。
- 不使用它们已经封装好的 Agent 主循环、tool calling runtime、memory runtime 或自动规划执行器。
- 可以使用 DeepSeek API 原生工具调用能力。模型与工具之间的协议使用 OpenAI-compatible `tools/tool_calls`，但工具注册、工具执行、循环控制、memory 和 trace 仍由本项目自己实现。
- 本项目需要自己实现最小 agent loop：
  1. 接收用户输入。
  2. 读取 session / memory / task state。
  3. 调用真实 LLM API，并传入本地工具的 `tools` schema。
  4. 读取模型返回的 assistant message，判断是直接回答，还是包含 `tool_calls`。
  5. 执行工具并记录 trace。
  6. 把工具结果以 `role=tool` 消息追加回上下文。
  7. 循环直到输出最终答案或触发最大步数收束策略。

因此 OpenHands SDK、Claude Agent SDK 里现成的 agent loop 不作为核心 runtime 使用。核心 loop、工具调度、session 维护、trace 日志需要自己写。

## 2. 最小目标

用 Python 实现一个命令行可运行的最小 Agent，满足笔试要求：

- 支持多轮对话。
- 支持 session 维护。
- 使用真实 LLM API，计划使用 DeepSeek API。
- `.env` 中配置 API 地址、模型名和 key。
- 自建 agent loop，不依赖现成 Agent 框架。
- 至少 3 个工具。
- 有最大步数限制。
- 有基本异常处理。
- 有工具调用 trace / 执行日志。
- 支持跨轮次继续执行的任务状态。
- 提供 README、Prompt 与问题解决记录、录屏说明。

展示形式建议：

- 保留终端 CLI 入口，方便展示 agent loop、trace 日志和调试过程。
- 额外提供一个简单网页入口，方便录屏演示多轮对话和 session 状态。
- CLI 和网页共用同一套 `AgentRuntime`，避免把核心逻辑写两遍。

## 3. 计划目录结构

```text
chat_agent/
  README.md
  TASK_BREAKDOWN.md
  PROMPTS_AND_NOTES.md
  .env.example
  requirements.txt
  src/
    main.py
    web.py
    agent/
      runtime.py
      llm.py
      memory.py
      schemas.py
      trace.py
    tools/
      calculator.py
      search.py
      todo.py
      registry.py
  data/
    sessions/
    traces/
```

说明：

- `src/agent/runtime.py`：核心 agent loop，自建。
- `src/agent/llm.py`：DeepSeek/OpenAI-compatible API 调用封装。
- `src/agent/memory.py`：session 文件读写、对话历史管理、结构化 memory 管理。
- `src/tools/`：工具实现，不做复杂框架。
- `src/web.py`：简单网页入口，只负责接收输入、展示回复和 trace，不负责 agent 核心逻辑。
- `data/sessions/`：保存每个 session 的对话历史和结构化 memory。二者在同一 session 文件中分字段存储，不混在同一个列表里。
- `data/traces/`：保存每轮工具调用日志。

## 4. 功能拆解

### 4.1 环境与工程初始化

- 创建 `requirements.txt`。
- 创建 `.env.example`，包含：
  - `DEEPSEEK_API_KEY`
  - `DEEPSEEK_BASE_URL`
  - `DEEPSEEK_MODEL`
  - `TAVILY_API_KEY`
  - `MAX_AGENT_STEPS`
- 确认使用 conda 环境：`mcp-learn`。
- README 中写明运行前需要：
  - `conda activate mcp-learn`
  - `pip install -r requirements.txt`
  - 复制 `.env.example` 为 `.env` 并填写 key。

### 4.2 LLM API 封装

- 使用 OpenAI-compatible chat completions 接口调用 DeepSeek。
- 输入：messages。
- 输入工具定义：OpenAI-compatible `tools` schema。
- 输出：完整 assistant message，包括 `reasoning_content`、正式回答 `content` 和可能存在的 `tool_calls`。
- 默认保留 DeepSeek thinking mode，不为了测试或实现方便关闭思考。
- 处理：
  - API key 缺失。
  - 网络异常。
  - 非 2xx 响应。
  - HTTP 响应 JSON 解析异常。

### 4.3 工具设计

至少实现 3 个工具：

1. `calculator`
   - 输入数学表达式。
   - 返回计算结果。
   - 做简单安全限制，只允许数字、运算符和括号。

2. `search`
   - 使用 Tavily Search API 实现真实搜索。
   - 从 `.env` 读取 `TAVILY_API_KEY`。
   - 输入查询关键词，可选结果数量。
   - 返回搜索标题、URL 和摘要。
   - 用于展示 agent 调用真实外部信息源的能力。

3. `todo`
   - 创建任务、查询任务、更新任务状态。
   - 支持跨轮次状态保存。
   - 用于满足“第一轮发起任务，第二轮追问进度”的要求。

可选增强：

- `read_docs`：读取本地 `docs` 文档。
- `weather`：mock 天气。

### 4.4 Agent Loop

核心循环放在 `AgentRuntime.run_turn()`：

1. 加载指定 session。
2. 追加用户输入到历史。
3. 组合 system prompt、历史消息、当前任务状态。
4. 从 tool registry 生成 DeepSeek/OpenAI-compatible `tools` schema。
5. 调用 LLM。
6. 解析 assistant message：
   - `reasoning_content`：模型思考过程，用于调试和展示，不作为最终答案直接返回。
   - `content`：正式回答。
   - `tool_calls`：原生工具调用请求。
7. 如果 assistant message 没有 `tool_calls`，视为最终答案，保存 assistant 消息并返回。
8. 如果 assistant message 包含 `tool_calls`，保存 assistant tool-call message。
9. 逐个执行 `tool_calls` 对应的本地工具。
10. 记录工具 trace。
11. 将工具结果以 `role=tool` 消息加回上下文，包含对应的 `tool_call_id`。
12. 继续循环，直到最终答案或触发最大步数收束策略。

#### 4.4.1 Assistant message 与请求上下文细化

assistant 响应需要区分“本地完整记录”和“下次请求可发送上下文”：

- 本地完整记录：
  - 保存 `role=assistant`。
  - 保存模型正式回答 `content`。
  - 保存 `reasoning_content`，用于 CLI/Web 展示和调试回看。
  - 保存原生 `tool_calls`，用于工具执行、trace 和问题复盘。
- 返回给用户：
  - 用户可见主回复只使用模型正式回答 `content`。
  - `reasoning_content` 可以作为调试区域、展开区域或日志字段展示，但不混入正式回答文本。
- 发送下一次 LLM 请求时：
  - 不把 `reasoning_content` 放入请求上下文。
  - 不把“仅用于本地展示的 assistant 完整记录”原样放入请求上下文。
  - 上下文只放三类消息：
    - 工具结果消息：`role=tool`。
    - 模型正式回答消息：`role=assistant` 且仅包含正式回答 `content`。
    - assistant 工具调用响应：`role=assistant`，包含对应的 `tool_calls`，不携带 `reasoning_content`。
  - assistant `tool_calls` 响应必须保留，因为 `role=tool` 工具结果需要能对应到模型发起的 `tool_call_id`，也方便多轮上下文中复盘工具调用链路。

建议新增一个上下文组装函数，例如：

```text
build_llm_context(session_messages, memory_summary) -> list[dict]
```

验收点：

- session JSON 中能看到 assistant 的 `reasoning_content`。
- CLI/Web 能展示 assistant 的 `reasoning_content`。
- 调 LLM 的请求 payload 中不包含 `reasoning_content`。
- 调 LLM 的请求 payload 不直接复用本地 assistant 完整记录。
- 请求上下文包含工具消息、模型正式回答消息和 assistant `tool_calls` 响应消息。
- assistant `tool_calls` 响应消息需要保留 `tool_call_id`、工具名和参数，且不携带 `reasoning_content`。

工具 schema 示例：

```json
{
  "type": "function",
  "function": {
    "name": "calculator",
    "description": "Calculate a simple arithmetic expression.",
    "parameters": {
      "type": "object",
      "properties": {
        "expression": {
          "type": "string",
          "description": "Arithmetic expression, such as (12 + 8) * 3"
        }
      },
      "required": ["expression"]
    }
  }
}
```

最大步数默认 5，可通过 `.env` 配置。

最大步数收束策略：

- `MAX_AGENT_STEPS` 表示单轮用户输入中最多允许执行的 agent 决策步骤。
- 当执行到最大步数且最近一步产生了工具结果时，不立刻返回失败。
- 先在工具结果后追加一条内部用户提示，要求模型基于当前已有信息给出最终答案，不再调用工具。
- 内部用户提示示例：

```text
已达到本轮最大推理步数限制。请不要再调用工具，请根据当前已有的对话历史和工具结果给出最终答案。如果信息不足，请说明当前能确定的内容和缺失的信息。
```

- 这次收束调用不再传入 `tools`，避免模型继续发起工具调用。
- 如果模型仍然没有给出可用文本答案，则 agent 返回兜底答案，说明已达到最大步数，并总结已有 observation。

### 4.5 Session 与 Memory

对话记录和 session memory 不是同一个概念，本项目采用“同一 session 文件、不同字段分区存储”的方式，保持实现简单，同时避免把结构化状态混入聊天流水。

采用 JSON 文件存储：

```json
{
  "session_id": "default",
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

字段说明：

- `messages`：对话历史，用于短期上下文召回，保存 user / assistant / tool-call / tool result 等消息。
- `memory.tasks`：结构化任务状态，用于跨轮次继续执行，例如任务 ID、标题、状态、进度、更新时间。
- `memory.facts`：可选，保存用户明确表达过且相对稳定的信息。
- `memory.preferences`：可选，保存用户偏好；本项目可先保留字段，不做复杂抽取。
- `metadata`：session 创建和更新时间。

召回时机：

- 每轮用户输入开始时，加载当前 session 文件。
- 调 LLM 前，把最近若干条 `messages` 放进上下文。
- 调 LLM 前，把 `memory.tasks` 摘要作为额外上下文注入 system/developer 风格提示中，避免直接伪装成用户消息。
- 工具执行后，如果工具改变结构化状态，例如 `todo` 创建或更新任务，立即更新 `memory.tasks`。
- 最终回答后，再保存 assistant message。

放置方式：

- 对话历史放在 `messages`。
- 跨轮次任务状态放在 `memory.tasks`。
- 对话历史和结构化 memory 逻辑分离，虽然物理上可以保存在同一个 session JSON 文件里。
- 工具执行日志单独写入 `data/traces/`，避免污染主对话历史。

#### 4.5.1 本地消息存储细化

`messages` 保存本地完整聊天流水，不等同于直接发给模型的上下文。

建议 message 结构：

```json
{
  "role": "assistant",
  "content": "正式回答文本",
  "reasoning_content": "模型思考过程，仅本地保存和展示",
  "tool_calls": [],
  "metadata": {
    "created_at": "...",
    "message_type": "assistant_response"
  }
}
```

存储规则：

- user 消息按用户输入保存。
- assistant 消息保存正式回答 `content` 和 `reasoning_content`。
- assistant 工具调用消息保存 `tool_calls`，方便复盘模型为何调用工具，并为后续 `role=tool` 消息提供对应关系。
- tool 消息保存 `role=tool`、`tool_call_id`、工具名和工具结果。
- session memory 读取后，需要通过上下文组装函数转换为 LLM 请求消息，不能把本地 `messages` 原样发送。

展示规则：

- CLI 主输出只展示正式回答。
- Web 聊天主体只展示正式回答。
- `reasoning_content` 放在可选调试区域、详情区域或 trace 附近展示。
- 工具结果和工具调用 trace 可以独立展示，避免混入 assistant 正式回复。

### 4.6 Trace / 日志

每次工具调用记录：

- `session_id`
- `turn_id`
- `step`
- `tool`
- `arguments`
- `result`
- `error`
- `timestamp`

终端也打印简洁 trace，便于录屏展示。

### 4.7 CLI 交互

`src/main.py` 提供命令行入口：

- 默认 session：`default`
- 支持传入 session：

```bash
python -m src.main --session demo
```

交互示例：

```text
You: 帮我创建一个任务：调研 Agent runtime
Agent: 已创建任务 ...

You: 这个任务现在进度怎么样？
Agent: 我查到当前任务状态是 ...
```

### 4.8 简单网页交互

计划使用 `streamlit` 做一个最小网页，原因是实现成本低，适合笔试录屏：

- 左侧选择或输入 `session_id`。
- 中间展示多轮对话。
- 底部输入用户消息。
- 页面上展示最近一次工具调用 trace。
- 所有请求仍然调用 `AgentRuntime.run_turn()`，网页不实现 agent loop。

运行方式示例：

```bash
streamlit run src/web.py
```

网页只作为展示层，不使用现成 Agent 框架。

### 4.9 README 内容

README 至少包含：

- 项目简介。
- 功能清单。
- 运行方式。
  - CLI：`python -m src.main --session demo`
  - Web：`streamlit run src/web.py`
- `.env` 配置说明。
- 系统设计。
- Agent loop 流程图或文字流程。
- Memory 的召回时机与放置方式。
- 工具列表。
- 示例对话。
- 录屏建议：
  - 启动项目。
  - calculator 调用。
  - search 调用。
  - todo 跨轮次继续执行。
  - trace 日志展示。

### 4.10 Prompt 与问题解决记录

创建 `PROMPTS_AND_NOTES.md`，记录：

- 给 LLM 的 system prompt。
- DeepSeek/OpenAI-compatible tool schema。
- 开发中遇到的问题。
- 如何解决：
  - HTTP 响应 JSON 解析失败。
  - 工具参数解析失败。
  - 工具异常。
  - session 文件不存在。
- 达到最大步数后的收束提示与兜底处理。

## 5. 实施步骤

### 5.1 开发与测试约定

- 每完成一个功能步骤，如果涉及代码功能，需要同步生成或更新合适的测试文件。
- 测试文件放在 `tests/` 下，命名尽量对应当前模块，例如：
  - `src/agent/config.py` 对应 `tests/test_config.py`
  - `src/agent/llm.py` 对应 `tests/test_llm_client.py`
  - `src/tools/registry.py` 对应 `tests/test_tool_registry.py`
- 每个步骤完成后，优先只运行当前步骤相关测试文件，不默认运行所有测试。
- 指定测试文件运行示例：

```bash
conda run -n mcp-learn pytest tests/test_tool_registry.py -q
```

- 如果一个步骤涉及多个模块，只运行这些模块对应的测试文件，例如：

```bash
conda run -n mcp-learn pytest tests/test_config.py tests/test_llm_client.py -q
```

- 只有在以下情况才运行全量测试：
  - 阶段性收尾。
  - 修改了共享模块或基础 schema。
  - 修改影响多个功能边界。
  - 用户明确要求全量测试。
- 测试结果需要记录到 `TASK_TRACKING.md`，包括测试命令、测试结果和当前步骤完成状态。

### 5.2 具体实施步骤

1. 初始化工程文件。
2. 实现 `.env` 配置读取。
3. 实现 LLM client。
4. 实现 tool registry。
5. 实现 `calculator`。
6. 实现 `search` Tavily 工具。
7. 实现 `todo` 和任务状态存储。
8. 实现 session memory。
9. 实现 trace logger。
10. 实现 agent runtime loop。
11. 实现 CLI。
12. 实现简单 Streamlit Web 页面。
13. 补充 README。
14. 补充 Prompt 与问题解决记录。
15. 用 `mcp-learn` 环境跑通 CLI 示例。
16. 用 `mcp-learn` 环境跑通 Web 示例。
17. 根据终端和网页展示准备录屏。

## 6. 验收用例

### 6.1 直接回答

用户：

```text
你好，介绍一下你能做什么
```

预期：

- Agent 直接回答。
- 不调用工具。

### 6.2 calculator

用户：

```text
帮我算一下 (12 + 8) * 3
```

预期：

- Agent 调用 `calculator`。
- trace 中出现工具调用记录。
- Agent 基于工具结果回答 `60`。

### 6.3 search

用户：

```text
搜索一下 DeepSeek API 怎么调用
```

预期：

- Agent 调用 `search`。
- `search` 使用 Tavily API 获取真实搜索结果。
- Agent 总结搜索结果。

### 6.4 跨轮次 todo

第一轮：

```text
帮我创建一个任务：调研最小 Agent runtime，状态先设为进行中
```

第二轮：

```text
刚才那个任务进度怎么样？
```

预期：

- 第一轮创建任务并保存到 `memory.tasks`。
- 第二轮从当前 session 的 `memory.tasks` 读取已有任务状态。
- Agent 不把第二轮当成全新问题。

### 6.5 最大步数

构造一个模型多次调用工具的场景。

预期：

- 达到最大步数后，agent 在最后一个工具结果后追加内部用户提示。
- 收束调用不再传入 `tools`。
- 模型应基于已有信息给出最终答案。
- 如果模型没有返回可用文本答案，则返回兜底答案。
- trace 中保留已执行步骤。

## 7. 后续可选优化

- 增加工具参数 schema 校验。
- 增加 `read_docs` 工具读取本地文档。
- 增加简单测试。
- 增加 trace pretty print。
- 增加 session 列表和清理命令。
