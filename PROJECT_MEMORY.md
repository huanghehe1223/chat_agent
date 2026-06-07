# 项目记忆

用于记录当前项目中已经确认过、后续开发需要默认遵守的约束和经验。

## DeepSeek Thinking 与 Tool Choice

- 默认开启 DeepSeek thinking mode：
  - 调用 LLM 时优先保留 `extra_body={"thinking": {"type": "enabled"}}`。
  - `reasoning_content` 只用于调试、日志和展示，不作为最终用户答案直接返回。

- `tool_choice` 使用默认行为：
  - 不显式设置 `tool_choice`，让 DeepSeek 使用默认/auto 工具选择。
  - 如果需要让模型调用某个特定工具，不要在 `tool_choice` 里指定工具名。
  - 可通过只传入目标工具的 `tools` schema 来约束模型只能调用该工具。

- 已确认约束：
  - DeepSeek thinking mode 不支持显式指定具体工具的 `tool_choice`。
  - 例如不要这样调用：

```python
tool_choice = {"type": "function", "function": {"name": "calculator"}}
```

- 推荐做法：

```python
message = client.chat_parsed(
    messages=messages,
    tools=[calculator_tool_schema],
    max_tokens=1000,
    extra_body={"thinking": {"type": "enabled"}},
)
```

这样可以保留 thinking mode，同时通过只提供一个工具 schema 来约束模型调用目标工具。

## 测试运行策略

- 非必要不跑全量 `pytest`。
- 每次功能改动后，优先只运行与本次改动直接相关的测试文件。
- 只有在以下情况才跑全量测试：
  - 用户明确要求跑全量。
  - 修改了共享核心模块，影响面跨 CLI、Web、runtime、memory、tools 等多个边界。
  - 阶段性收尾，需要确认整体回归。
  - 相关测试通过但仍存在明显的跨模块风险。
- 记录验证结果时，优先记录本次相关测试；全量测试要说明为什么必要。
