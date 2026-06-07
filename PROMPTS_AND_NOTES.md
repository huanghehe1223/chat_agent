# AI Prompt 与问题解决记录

本文用于整理本项目开发过程中的 AI 协作方式、关键 prompt、问题修正记录和测试策略。原始对话记录保存在本地 `codex_sessions/` 目录中，内容较长且包含大量工具输出；本文做提交友好的提炼，重点说明人的设计判断、任务拆解、持续纠偏和最终实现如何落地。

## 1. 协作方式概览

本项目不是一次性让 AI 生成完整 Agent，而是采用“人工拆解任务 + 模块化实现 + 单元测试验证 + tracking 跨 session 追踪”的方式推进。

核心协作节奏：

1. 先理解题目边界，明确不能直接使用 LangChain / OpenHands / Claude Agent SDK 这类现成 Agent loop。
2. 将项目拆成配置、LLM API、工具、memory、runtime、CLI、trace、Web、README 等子任务，写入 [TASK_BREAKDOWN.md](TASK_BREAKDOWN.md)。
3. 每完成一个功能模块，就补充对应测试，只运行相关测试文件，避免无关全量测试拖慢开发。
4. 用 [TASK_TRACKING.md](TASK_TRACKING.md) 记录当前完成状态、测试命令、测试结果和设计决策，保证跨 session 后仍能继续协作。
5. 在实现过程中持续检查 AI 方案是否符合 Agent 原理和题目要求，对偏离预期的地方及时修正。

这套方式让 AI 更像执行和实现助手：我负责定义边界、提出验收标准、发现不合理设计并纠偏；AI 负责根据当前上下文实现代码、补测试、更新文档。

## 2. 关键 Prompt 片段

以下是开发过程中较关键的人工指令，按主题整理。

### 2.1 题目边界与自建 runtime

最开始先确认题目中“核心 runtime 需要自己实现”的含义。我明确要求：

```text
"框架完成主流程（如 LangChain / OpenHands 等），核心 runtime 需要自己实现"
请问这句话是什么意思，OpenHands sdk，claude agent sdk，里面有现成的agent loop，能用吗，核心runtime必须自己构建agent loop吗
要自建哦
```

最终设计结论：

- 可以使用普通依赖库和 OpenAI-compatible LLM SDK。
- 不使用现成 Agent 框架完成主循环、工具调度、memory runtime 或规划执行。
- `AgentRuntime.run_turn()` 自己实现接收输入、判断工具调用、执行工具、写回工具结果、继续循环和最终回答。

### 2.2 任务拆解、测试与 tracking

项目开始时我没有直接让 AI 写完整代码，而是先要求任务拆解：

```text
完成这个小项目
进行任务拆解，写到对应文档（md）里面，不需要太复杂，完成基本要求即可
python实现，.env里面配置api和key
先进行任务拆解，后续再一步一步完成，用mcp-learn这个conda环境
```

随后进一步要求：

```text
完成某个步骤的话，如果涉及功能内容的话，生成相应的测试文件，测试该步骤是否达到预期效果，并且生成一个任务追踪文件，记录当前任务完成情况，供后续跨session协作使用
```

由此形成两个工程管理文件：

- [TASK_BREAKDOWN.md](TASK_BREAKDOWN.md)：记录任务拆解、设计边界、验收用例和开发顺序。
- [TASK_TRACKING.md](TASK_TRACKING.md)：记录每个模块完成情况、测试命令、测试结果、后续决策。

后续我又补充测试策略：

```text
在任务拆解里面写下完成某个任务之后，要进行生成合适的测试文件测试是否能达到预期效果，并且测试的时候只测试特定文件，不需要pytest所有文件
```

这让开发节奏变成“一个模块一个闭环”，避免到最后才发现集成问题。

### 2.3 使用真实 API 与 OpenAI SDK

在 LLM 封装阶段，我要求真实请求而不是 mock：

```text
不需要，直接真实发送请求就行，后续key我会进行注销的，不要mock，直接真实环境
```

同时也纠正了“不必要重复造轮子”的实现方向：

```text
可以用openai sdk，没必要重复造轮子
```

最终实现：

- `src/agent/llm.py` 使用 `openai` SDK 调用 DeepSeek OpenAI-compatible API。
- runtime 和测试都走真实模型能力，尤其验证 thinking、stream 和 tool_calls 行为。

### 2.4 DeepSeek thinking 与 tool_choice 约束

开发中 AI 曾为了测试方便关闭 thinking。我指出这不符合项目预期：

```text
什么情况，你需要正常解析think过程和正式回答过程啊，默认就需要思考
```

随后又根据 DeepSeek 约束调整工具测试策略：

```text
DeepSeek 返回了一个很有用的约束：开启 thinking mode 时不支持显式 tool_choice。
创建当前项目的记忆md，写明默认开启thinking，tool_choice设置成auto（huoz 不设置用默认的），不能在tool_choice里面指定用特定工具
```

最终实现：

- 默认开启 thinking mode。
- 解析并保存 `reasoning_content`，但不把它作为正式回答。
- 不显式指定某个 `tool_choice`。
- 测试某个工具时，只传目标工具 schema 来约束模型调用。

### 2.5 原生 tool_calls，而不是自定义 JSON

在工具调用协议上，我修正了早期“让模型输出固定 JSON”的倾向：

```text
不对啊，deepseek api本身就支持工具调用，直接用原生工具调用就行啊，没必要限制模型输出格式
```

最终实现：

- tool schema 使用 OpenAI-compatible `tools` 格式。
- runtime 读取 assistant message 中的原生 `tool_calls`。
- `ToolRegistry` 根据 `tool_calls[].function.name` 和 `arguments` 执行本地工具。
- 工具结果以 `role=tool` 写回上下文，继续下一轮 LLM。

### 2.6 流式解析从“最终合并”改为“逐 chunk 事件”

我发现早期流式实现只是收集完整 chunks 后再合并，不符合真实流式 Agent 行为，于是明确给出正确流程：

```text
流式解析有点问题
现在是：
DeepSeek stream -> 收集全部 chunks -> 合并 reasoning_content / content / tool_calls -> 返回完整结果
整个流式结束之后才能拿到各个内容的解析

正确应该是：
DeepSeek stream -> 每来一个 chunk 就解析 delta
reasoning_content delta：立即按思考流输出
content delta：立即按正式回答流输出
tool_calls delta：先累积
tool_call 完整后：触发工具调用
工具结果 append 到 messages
继续下一轮 LLM stream
```

最终实现：

- `DeepSeekClient.stream_chat_events()` 逐 chunk 产出事件。
- 事件类型包括 `reasoning_delta`、`content_delta`、`tool_call_delta`、`tool_call` 和 `message`。
- CLI/Web 可以实时展示 reasoning、正式回答、tool_use 和 tool_result。

### 2.7 Memory 与对话历史分离

我主动提出 memory 设计问题：

```text
有关memory的处理有点奇怪，对话记录和会话memory不是一个东西吧，存储在一起合适吗，我了解task状态一般是通过session memory实现的
```

最终实现采用“同一 session 文件、不同字段分区存储”：

- `messages` 保存本地聊天流水。
- `memory.tasks` 保存结构化任务状态。
- `build_llm_context()` 负责把本地消息转换成 LLM 请求上下文。
- `reasoning_content` 和本地 `metadata` 不发送给模型。
- `memory.tasks` 在每轮 LLM 调用前以摘要形式注入 system prompt。

### 2.8 todo 工具改为 session 级完整列表同步

早期 todo 工具采用的是一个 CRUD 式 schema：

```text
todo(action=create/list/update, title?, status?, task_id?)
```

这个设计表面上只有一个工具，实际把“创建任务、查询任务、更新任务状态”三类能力揉在了一起，几乎等价于把 3 个工具融合成 1 个复杂工具。它的问题是 schema 描述不够清晰：不同 action 需要不同参数组合，`title` 有时用于创建、有时用于 update lookup，`status` 有时可选、有时必填，`list` 又主要服务 UI 展示而不是模型推理。这样的工具虽然工程上能实现，但模型可能无法稳定理解什么时候该调用、该带哪些字段，也容易出现只口头说明任务完成却没有正确更新状态的问题。

我在对话里进一步指出：todo 的状态展示和状态管理应该拆开理解。模型不需要频繁调用 `list` 去“看任务列表”，因为当前任务状态可以通过对话上下文和 session memory 摘要提供；CLI/Web 想展示 task list 时，也应该由 Agent 系统读取 session memory，而不是依赖模型再调用一个 `list` action。

```text
todo工具应该是和session绑定的吧
tool不需要list吧，模型有上下文，是一直知道有哪些task，每个task的状态
这个list应该是agent系统想进行任务状态显示的时候调用的吧
```

因此后续设计从“一个复杂 CRUD 工具”改成“一个状态快照同步工具”：模型只负责提交当前 session 的完整任务列表，runtime 负责校验、持久化和展示事件。也就是改成 `manage_todo_list(todoList=[...])` 形式：

```text
直接开始完善todo 这个工具(manage_todo_list的形式)，实现在session级别的记忆
cli任务list读取展示
session初始化的时候读取一下list记忆进行展示
```

最终实现：

- 工具名为 `manage_todo_list`。
- 工具 schema 只表达一件事：提交完整 `todoList`。
- 任务状态统一为 `not-started`、`in-progress`、`completed`。
- runtime 校验完整列表，例如任务 id 唯一、最多一个任务处于 `in-progress`。
- runtime 执行工具后写入当前 session 的 `memory.tasks`。
- CLI/Web 读取 session memory 展示 task list，不要求模型调用 `list`。
- CLI 启动 session 时展示 task list，工具调用更新后立即展示最新状态。
- Web 左侧 task list 从 session 持久化文件读取，并在 `manage_todo_list` 调用后实时刷新。

后续真实使用时，我又发现模型创建任务后可能只在文字里说“第一个任务完成”，但没有再次调用工具写回状态。因此继续通过 system prompt、工具 schema 和 memory 摘要强化协议：创建任务列表时必须调用 `manage_todo_list`；任务开始前要把对应任务标记为 `in-progress` 并提交完整列表；任务完成后、最终回答前要再次提交完整列表，把任务标记为 `completed`。这样任务状态不会停留在自然语言回复里，而会真正进入 session memory，支持下一轮继续执行。

### 2.9 最大步数收束策略

我进一步明确 `MAX_AGENT_STEPS` 不是简单失败退出，而是要能收束：

```text
更新一下任务，如果超出推理步数限制，能否在tool_result后面加一个user_prompt，讲明已经达到最大推理步数，请根据当前已有信息给出最终答案
```

最终实现：

- 单轮最多执行 `MAX_AGENT_STEPS` 个 Agent 决策步骤。
- 达到上限且已有工具结果时，追加内部提示：

```text
已达到本轮最大推理步数限制。请不要再调用工具，请根据当前已有的对话历史和工具结果给出最终答案。如果信息不足，请说明当前能确定的内容和缺失的信息。
```

- 收束调用不再传入 `tools`，避免继续工具循环。

### 2.10 Web 页面体验迭代

Web 不是一次性完成，而是在真实使用中多轮修正：

- 修复 `ModuleNotFoundError: No module named 'src'`。
- 增加新建 session、指定 session 名称、中文 session。
- 刷新页面后保持当前 session。
- session 按时间顺序展示。
- 增加删除当前 session，并同步删除 session、Req/Res 日志和 trace。
- Req/Res 日志默认不渲染大 JSON，避免页面卡顿。
- `tool_result` 使用系统图标，但保持原对话块展示形式。
- 历史气泡默认折叠；流式过程中先展开，阶段结束后自动折叠。
- task list 侧边栏增强状态展示，并在 `manage_todo_list` 调用后立即读取持久化文件刷新。

这些迭代体现了项目不是只满足“能跑”，还关注可演示性和录屏效果。

## 3. Runtime Prompt 摘要

当前 runtime 的 system prompt 位于 `src/agent/runtime.py`，核心约束包括：

- 需要计算、搜索或管理任务时调用工具。
- 工具返回结果后，基于结果给出简洁正式回答。
- 不把 `reasoning_content` 当作正式回答输出。
- search 只在用户明确要求搜索、问题有实时性、或模型知识不足时使用。
- 用户要求创建任务列表或多步骤任务时，必须先调用 `manage_todo_list`。
- 任务开始或完成时，必须再次调用 `manage_todo_list` 写回完整列表。
- 不允许只在文字中声明任务完成，任务状态必须通过工具提交。

最大步数收束 prompt：

```text
已达到本轮最大推理步数限制。请不要再调用工具，请根据当前已有的对话历史和工具结果给出最终答案。如果信息不足，请说明当前能确定的内容和缺失的信息。
```

## 4. 工具 Schema 摘要

工具 schema 由 `src/tools/registry.py` 统一注册并导出。

`calculator`

- 输入：`expression`
- 作用：计算简单数学表达式。
- 安全策略：`src/tools/calculator.py` 使用 AST allowlist，不使用 `eval`。

`search`

- 输入：`query`、`max_results`
- 作用：通过 Tavily 搜索返回标题、URL 和摘要。
- 使用策略：只在用户明确要求联网、问题依赖实时信息，或模型知识不足时调用。

`manage_todo_list`

- 输入：完整 `todoList`
- 作用：管理 session 级任务列表。
- 状态：`not-started`、`in-progress`、`completed`
- 约束：同一时间最多一个任务为 `in-progress`；任何状态变化都提交完整列表。

## 5. 问题解决记录

| 问题 | 判断与修正 | 最终落地 |
| --- | --- | --- |
| 是否能使用现成 Agent 框架 | 明确核心 runtime 必须自建，普通 SDK 可以用 | 自建 `AgentRuntime`，只使用 OpenAI SDK 调 LLM |
| LLM API 是否 mock | 要求真实 DeepSeek API 请求 | `tests/test_llm_client.py` 和工具调用测试走真实模型 |
| 是否关闭 thinking 以便测试 | 指出默认必须保留思考过程 | 解析 `reasoning_content` 与正式 `content` |
| DeepSeek thinking 下强制 tool_choice 报错 | 不强制指定工具，改为只传目标 schema | 测试中保持 thinking mode，同时验证工具调用 |
| 工具调用协议是否自定义 JSON | 改为 DeepSeek 原生 `tool_calls` | `ToolRegistry.execute_tool_call()` 执行本地工具 |
| 流式响应只是最终合并 | 改为逐 chunk 解析 delta | CLI/Web 实时展示 reasoning、content、tool_use |
| 对话历史与 memory 混在一起 | 分清本地消息流水和结构化 memory | `messages` 与 `memory.tasks` 分区保存 |
| todo 工具是否独立文件持久化 | 改为 session 级任务状态 | `manage_todo_list` 写入当前 session memory |
| 达到最大步数是否直接失败 | 改为追加内部收束提示 | 不传 tools 的最终 LLM 调用生成兜底答案 |
| 工具 trace 是否和 session 混在一起 | trace 做汇总日志 | `data/traces/{session_id}.trace.log` |
| Web Req/Res 渲染卡顿 | 默认不读取大 JSON，按需加载原始日志 | 页面流畅优先 |
| task list 是否只在整轮结束后更新 | 工具调用后立即读持久化文件刷新 | Web 侧 task panel 实时更新 |

## 6. 测试与验证策略

测试策略贯穿整个开发过程：

- 配置读取：`tests/test_config.py`
- LLM 流式解析：`tests/test_llm_client.py`
- 工具注册和执行：`tests/test_tools.py`
- 真实 LLM 工具调用：`tests/test_llm_tool_execution.py`
- session memory：`tests/test_memory.py`
- AgentRuntime loop：`tests/test_runtime.py`
- CLI 展示：`tests/test_cli.py`
- trace 日志：`tests/test_trace.py`
- Web helper：`tests/test_web.py`

测试原则：

- 每完成一个功能模块就补相关测试。
- 平时优先运行当前模块相关测试。
- 修改共享模块或阶段性收尾时才运行全量测试。
- 测试命令和结果记录到 [TASK_TRACKING.md](TASK_TRACKING.md)，方便后续 session 继续接手。

## 7. 开发结果

最终项目完成了笔试要求的核心能力：

- 多轮对话和 session 维护。
- 自建 Agent loop。
- 真实 DeepSeek LLM API。
- `calculator`、`search`、`manage_todo_list` 三个工具。
- 原生 tool_calls 解析和本地工具执行。
- 最大步数限制与收束策略。
- 异常处理和工具 trace。
- 跨轮次任务状态继续执行。
- CLI 和 Web 两种展示方式。

整体协作过程体现为：人负责拆解、约束、判断和验收；AI 负责实现、测试和文档更新；通过 `TASK_BREAKDOWN.md` 与 `TASK_TRACKING.md` 保持长期上下文，最后完成集成与录屏展示。
