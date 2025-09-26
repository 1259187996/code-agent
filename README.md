# 运行方法

首先请确保你已经安装了 uv，如果没有的话，请按以下页面的要求安装：

https://docs.astral.sh/uv/guides/install-python/

然后在当前目录下，新建一个叫做 .env 的文件，输入以下内容：

```
DEEPSEEK_API_KEY=你的DeepSeek API Key
```

如果你之前使用 OpenRouter，现在已经改为使用 DeepSeek 官方 API（base_url: https://api.deepseek.com）。

确保 uv 已经安装成功后，进入到当前文件所在目录，然后执行以下命令即可启动：

```bash
uv run agent.py /absolute/path/to/your/project
```

模型与接口说明：本项目默认模型为 `deepseek-chat`，请求格式遵循 DeepSeek Chat Completions API。

## 会话模式（REPL）

安装/准备完成后，可以使用会话模式直接进入多轮任务交互：

```bash
uv run codeagent
恢复会话：

```bash
# 指定会话 ID 加载
codeagent --load s_20250926_095037

# 恢复最近一次
codeagent --resume-last
```
```

- 默认使用当前工作目录作为项目目录安全边界
- 多次输入任务相互独立（本阶段不保留跨轮记忆）
- 退出：输入 `/exit` 或使用 `Ctrl+C`/`Ctrl+D`

项目结构已模块化：

```
code_agent/
  ├─ cli.py           # 会话入口
  ├─ agent.py         # ReActAgent 实现
  ├─ session.py       # 会话存储（messages/summary/config）
  ├─ memory.py        # 结构化记忆（memory.jsonl 持久化与检索）
  ├─ tools.py         # 工具封装（读写文件、终端命令）
  └─ prompt.py        # 系统提示构建
agent.py              # 兼容旧入口（代理到 code_agent.cli.chat）
```

结构化记忆：
- 每轮结束从“用户输入+最终回答”抽取 0~3 条短句记忆，去重后写入 `.codeagent/memory.jsonl`
- 每次新任务按关键词/重要度/新近性检索 Top-K 记忆并注入到系统提示前缀
- 目前为简易关键词检索，后续可扩展为向量检索

一次性模式（旧方式）仍可：

```bash
uv run agent.py
```