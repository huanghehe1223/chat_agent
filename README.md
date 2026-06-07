# Minimal Agent

一个从零实现的最小可用 Agent 项目。

当前状态：配置读取和 DeepSeek LLM API 封装已完成，核心 agent runtime 尚未实现。

## 计划运行方式

CLI：

```bash
conda activate mcp-learn
pip install -r requirements.txt
python -m src.main --session demo
```

Web：

```bash
conda activate mcp-learn
pip install -r requirements.txt
streamlit run src/web.py
```

## 配置

复制 `.env.example` 为 `.env`，并填写 DeepSeek API key。

```bash
copy .env.example .env
```

后续实现会从 `.env` 中读取：

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`
- `TAVILY_API_KEY`
- `MAX_AGENT_STEPS`

## 当前已完成

- `.env` 配置读取。
- OpenAI SDK 对接 DeepSeek API。
- 默认保留 DeepSeek thinking mode。
- 解析 assistant message 中的 `reasoning_content`、正式回答 `content` 和原生 `tool_calls`。

验证：

```bash
conda run -n mcp-learn pytest -q
```

当前结果：`7 passed`
