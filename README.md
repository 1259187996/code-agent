# CodeAgent · 会话式代码智能体

CodeAgent 是一个基于 ReAct 的本地开发助手：支持会话模式、多轮任务、会话摘要持久化、结构化记忆与向量检索（可选）。适合在任意项目目录中进行“像 Claude Code 一样”的连续对话协作。

## 特性
- 会话模式：直接在命令行进入 REPL，多轮对话连续执行
- 会话摘要：自动将每轮结论提炼为摘要并回灌后续上下文
- 结构化记忆：跨会话可复用的“事实/约束/命名/契约”存储与检索
- 向量检索（可选）：使用小型本地向量库（FAISS + sentence-transformers）进行语义检索
- 安全沙箱：文件读写与命令执行仅允许在当前项目目录内，且必须使用绝对路径

## 环境要求
- Python ≥ 3.12
- 已安装 `uv`（推荐）：参考官方安装指南 `https://docs.astral.sh/uv/guides/install-python/`
- 已设置 DeepSeek API Key（仅环境变量方式）

## 1) 获取代码与本地安装
```bash
# 克隆仓库
git clone [<your-repo-url>](https://github.com/1259187996/code-agent.git) code-agent && cd code-agent

# 创建并激活虚拟环境
uv venv
source .venv/bin/activate

# 安装依赖（开发模式）
uv pip install -e .
```

## 2) 配置 API Key（必需）
仅支持环境变量方式：
```bash
export DEEPSEEK_API_KEY=你的Key
# 建议写入 ~/.zshrc 以便每次终端启动自动生效
# echo 'export DEEPSEEK_API_KEY=你的Key' >> ~/.zshrc && source ~/.zshrc
```

## 3) 本地使用（当前项目内）
在你的项目根目录执行：
```bash
codeagent
```
说明：
- 默认将“当前工作目录”作为 `project_dir` 安全边界
- 退出：输入 `/exit` 或使用 `Ctrl+C` / `Ctrl+D`

若尚未进行全局安装，可使用虚拟环境内脚本：
```bash
.venv/bin/codeagent
```

## 4) 全局安装（可在任意目录使用）
推荐其一：
```bash
# 方案 A：uv tool（类似 pipx）
uv tool install --force .
# 若提示未在 PATH，请把 ~/.local/bin 加入 PATH
# echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc

# 方案 B：pipx（需已安装 pipx）
pipx install .
```
安装完成后，在任意目录执行：
```bash
codeagent
```

## 5) 向量检索（可选）
首次启用向量检索时，建议为当前项目构建一次索引（会自动下载小模型，CPU 可用）：
```bash
codeagent --reindex-memory --embed-model all-MiniLM-L6-v2
```
日常使用直接：
```bash
codeagent
```
说明：
- 真值库：`./.codeagent/memory.jsonl`
- 向量索引：`./.codeagent/index/<模型名>/index.faiss`
- 首次重建后，新增记忆将自动“增量编码并写入索引”；检索会混合“向量相似度 + 重要度 + 新近性 + 关键词”进行重排
- 如切换向量模型（`--embed-model`），建议配合 `--reindex-memory` 重建索引

## 6) 会话管理
- 新建会话：直接运行 `codeagent` 即创建新会话目录 `./.codeagent/sessions/<session_id>/`
- 恢复已存在会话：
```bash
# 指定会话 ID 加载
codeagent --load s_YYYYMMDD_HHMMSS

# 恢复最近一次会话
codeagent --resume-last
```
会话目录结构（示例）：
- `./.codeagent/sessions/<session_id>/messages.jsonl`：原始消息（system/user/assistant/observation）
- `./.codeagent/sessions/<session_id>/summary.md`：会话摘要（每轮覆盖更新）
- `./.codeagent/sessions/<session_id>/config.json`：会话元数据

## 7) 命令速查
```bash
# 进入会话（当前目录作为项目根）
codeagent

# 指定向量模型并重建索引（首次 / 换模型 / 索引损坏时）
codeagent --reindex-memory --embed-model all-MiniLM-L6-v2

# 指定模型但不重建（不推荐长期这样使用）
codeagent --embed-model all-MiniLM-L6-v2

# 恢复会话
codeagent --load <session_id>
codeagent --resume-last

# 代码索引（区分于“向量记忆索引”）：
# 初始化/重建/查看统计；可用 --index-scope 限定范围（如 src）
# 可配置块大小与重叠（块级索引会生成 chunks.jsonl）
codeagent --index-init [--index-scope src] [--index-chunk-lines 300] [--index-chunk-overlap 50]
codeagent --index-rebuild [--index-scope src] [--index-chunk-lines 300] [--index-chunk-overlap 50]
codeagent --index-stats

# 接口索引（区分于“向量记忆索引/代码块索引”）：
# endpoints.jsonl：method/path/handler/preview
codeagent --index-init   # 会自动生成 endpoints
```

## 8) 常见问题
- 找不到 `codeagent` 命令：确认 `~/.local/bin` 已加入 PATH（或使用 `.venv/bin/codeagent`）。
- 提示未找到 `DEEPSEEK_API_KEY`：请先 `export DEEPSEEK_API_KEY=你的Key`，并考虑写入 `~/.zshrc`。
- 首次向量检索较慢：需下载小模型并构建索引，后续增量很快。
- 安全限制：工具仅允许绝对路径且必须位于 `project_dir` 内，避免误改他处文件。

---

