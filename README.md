# 运行方法

首先请确保你已经安装了 uv，如果没有的话，请按以下页面的要求安装：

https://docs.astral.sh/uv/guides/install-python/

然后在当前目录下，新建一个叫做 .env 的文件，输入以下内容：

```
DEEPSEEK_API_KEY=你的DeepSeek API Key
```


确保 uv 已经安装成功后，进入到当前文件所在目录，然后执行以下命令即可启动：

```bash
uv run agent.py /absolute/path/to/your/project
```

模型与接口说明：本项目默认模型为 `deepseek-chat`，请求格式遵循 DeepSeek Chat Completions API。

## 会话模式（REPL）

安装/准备完成后，可以使用会话模式直接进入多轮任务交互：

```bash
uv run codeagent
全局使用（推荐其一）：

1) 使用 uv tool（类似 pipx）：
```bash
uv tool install --force .
# 若提示未在 PATH，请把 ~/.local/bin 加入 PATH：
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
```

2) 使用 pipx：
```bash
pipx install .
```

然后在任意项目目录执行：
```bash
codeagent
```

API Key 配置（多种方式，按优先级读取）：
- 直接在 shell 导出：
```bash
export DEEPSEEK_API_KEY=你的Key
```
- 在项目根或全局放置 .env 文件（不会覆盖已导出的变量）：
```
./.env                     # 项目级
~/.codeagent/.env          # 用户级（推荐）
~/.config/codeagent/.env   # 用户级备用

# 内容：
DEEPSEEK_API_KEY=你的Key
```
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

