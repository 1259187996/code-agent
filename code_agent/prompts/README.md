# 多 Agent 提示词（中文）

本目录包含 4 个子代理的系统提示词，配合 Lead→Search→Edit→Shell 的软隔离流程使用。

- `LEAD_PROMPT.txt`：负责任务拆解/路由/整合，不直接改代码或跑命令
- `SEARCH_PROMPT.txt`：基于索引检索定位路径+行号+片段（优先 endpoints→symbols→chunks→files）
- `EDIT_PROMPT.txt`：在给定路径/行区间与约束下生成最小修改方案（结构化 edits JSON）
- `SHELL_PROMPT.txt`：受控执行命令，遵循确认策略（RUN_CMD_CONFIRM_MODE）并返回结构化结果

使用建议
- Lead 获取用户意图与会话摘要，输出 steps 计划 JSON；你据此依次调用对应子代理。
- 子代理只拿最小上下文（Top-K 记忆、必要片段/行号、限制范围）；避免传递整段会话。
- 交接均用结构化 JSON，降低误解与 token 消耗。
- 安全：严格遵守 project_dir 沙箱与绝对路径；Shell 遵循确认策略。
