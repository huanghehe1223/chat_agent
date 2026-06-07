# Prompt 与问题解决记录

## 当前状态

- 已完成工程初始化。
- Agent system prompt 尚未实现。
- DeepSeek/OpenAI-compatible LLM API 封装已实现。
- LLM 封装会解析 `reasoning_content`、正式回答 `content` 和原生 `tool_calls`。

## 后续记录项

- System prompt。
- 工具 schema，即 DeepSeek/OpenAI-compatible `tools` 定义。
- DeepSeek thinking mode 默认开启；测试和 runtime 都不关闭思考。
- `reasoning_content` 只用于调试和展示，正式对用户返回使用 `content`。
- Tavily search 工具的查询参数和结果摘要格式。
- HTTP 响应 JSON 解析失败处理。
- 工具参数解析失败处理。
- 工具异常处理。
- session 文件不存在处理。
- Memory 召回：最近若干条 `messages` 作为对话上下文，`memory.tasks` 摘要作为状态上下文；对话流水和结构化任务状态分开。
- 最大步数限制处理：达到上限后追加内部用户提示，并在收束调用时不再传入 `tools`，要求模型基于已有工具结果给最终答案；如果没有可用文本答案，则执行兜底返回。
