"""兼容旧入口：保留 agent.py 的 chat() 供 `agent:chat` 或直接导入。

新代码位于 `code_agent` 包。此处仅代理到 `code_agent.cli.chat`。
"""

from code_agent.cli import chat  # noqa: E402,F401
