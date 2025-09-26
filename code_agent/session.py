import os
import json
from datetime import datetime, timezone
from typing import Optional, Dict


class SessionStore:
    """管理会话持久化：messages.jsonl / summary.md / config.json。

    - 提供追加消息、读取/写入摘要、初始化会话目录等能力
    """

    def __init__(self, project_dir: str, session_id: Optional[str] = None):
        self.project_dir = os.path.abspath(project_dir)
        self.session_id = session_id or datetime.now(timezone.utc).strftime("s_%Y%m%d_%H%M%S")
        self.session_dir = os.path.join(self.project_dir, ".codeagent", "sessions", self.session_id)
        os.makedirs(self.session_dir, exist_ok=True)

        self.paths = {
            "messages": os.path.join(self.session_dir, "messages.jsonl"),
            "summary": os.path.join(self.session_dir, "summary.md"),
            "config": os.path.join(self.session_dir, "config.json"),
        }

    def init_config(self, model: str):
        data = {
            "project_directory": self.project_dir,
            "session_id": self.session_id,
            "model": model,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(self.paths["config"], "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def append_message(self, role: str, content: str):
        line = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "content": content,
        }
        with open(self.paths["messages"], "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def read_summary(self) -> str:
        if not os.path.exists(self.paths["summary"]):
            return ""
        try:
            with open(self.paths["summary"], "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""

    def write_summary(self, text: str):
        with open(self.paths["summary"], "w", encoding="utf-8") as f:
            f.write(text)

    def truncate_summary(self, text: str, max_chars: int = 2000) -> str:
        text = text.strip()
        if len(text) <= max_chars:
            return text
        return "…\n" + text[-max_chars:]

    def update_summary(self, user_input: str, final_answer: str):
        prev = self.read_summary()
        final_short = (final_answer or "").strip()
        if len(final_short) > 600:
            final_short = final_short[:600] + "…"
        new_block = [
            f"- 任务：{user_input}",
            f"- 结论：{final_short}",
        ]
        combined = (prev + "\n" if prev else "") + "\n".join(new_block)
        combined = self.truncate_summary(combined)
        self.write_summary(combined)


