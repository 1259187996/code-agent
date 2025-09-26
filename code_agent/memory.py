import os
import json
import re
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _tokenize(text: str) -> List[str]:
    # 粗略分词：字母数字 + 常见中日韩统一表意文字范围
    return re.findall(r"[\w\u4e00-\u9fff]+", text.lower())


class MemoryStore:
    """项目级结构化记忆的磁盘存储与检索（JSONL）。

    - 文件路径：<project_dir>/.codeagent/memory.jsonl
    - 字段：id, content, tags, importance, createdAt, lastUsedAt, sessionId, source
    - 检索：关键词 overlap + importance + 简单新近性
    """

    def __init__(self, project_dir: str):
        self.project_dir = os.path.abspath(project_dir)
        self.store_path = os.path.join(self.project_dir, ".codeagent", "memory.jsonl")
        os.makedirs(os.path.dirname(self.store_path), exist_ok=True)

    # 读写基础
    def _iter_items(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.store_path):
            return []
        items: List[Dict[str, Any]] = []
        with open(self.store_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
        return items

    def _append_item(self, item: Dict[str, Any]):
        with open(self.store_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    # 写入（带去重）
    def add_from_turn(self, user_input: str, final_answer: str, session_id: Optional[str] = None, k: int = 3):
        candidates = self._extract_candidates(user_input, final_answer, k=k)
        if not candidates:
            return
        existing = self._iter_items()
        existing_norm = { _normalize_text(it.get("content", "")): it for it in existing }
        now = _now_iso()
        for c in candidates:
            norm = _normalize_text(c)
            if not norm:
                continue
            if norm in existing_norm:
                # 触发使用更新时间与轻微抬升重要度
                item = existing_norm[norm]
                item["lastUsedAt"] = now
                item["importance"] = min(1.0, float(item.get("importance", 0.5)) + 0.05)
                # 全量重写（简单实现）
                self._rewrite_all(existing)
            else:
                item = {
                    "id": f"mem_{int(datetime.now(timezone.utc).timestamp())}",
                    "content": c,
                    "tags": [],
                    "importance": 0.6,
                    "createdAt": now,
                    "lastUsedAt": now,
                    "sessionId": session_id,
                    "source": "assistant_final_answer",
                }
                self._append_item(item)

    def _rewrite_all(self, items: List[Dict[str, Any]]):
        with open(self.store_path, "w", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")

    # 候选抽取（启发式）
    def _extract_candidates(self, user_input: str, final_answer: str, k: int = 3) -> List[str]:
        text = (final_answer or "").strip()
        if not text:
            return []
        # 先按行切分，再按句号补充
        parts: List[str] = []
        for line in text.splitlines():
            line = line.strip(" -•\t").strip()
            if not line:
                continue
            for seg in re.split(r"[。.!?；;]", line):
                seg = seg.strip()
                if 6 <= len(seg) <= 120:
                    parts.append(seg)
        # 选择前 k 条
        return parts[:k]

    # 检索
    def retrieve_topk(self, query: str, k: int = 5) -> List[str]:
        items = self._iter_items()
        if not items or not query.strip():
            return []
        q_tokens = set(_tokenize(query))
        if not q_tokens:
            return []

        def recency_score(dt_iso: str) -> float:
            try:
                dt = datetime.fromisoformat(dt_iso)
            except Exception:
                return 0.0
            delta = datetime.now(timezone.utc) - (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))
            if delta <= timedelta(days=7):
                return 1.0
            if delta <= timedelta(days=30):
                return 0.5
            return 0.1

        scored = []
        for it in items:
            content = it.get("content", "")
            tokens = set(_tokenize(content))
            overlap = len(q_tokens & tokens)
            importance = float(it.get("importance", 0.5))
            rec = recency_score(it.get("lastUsedAt", it.get("createdAt", _now_iso())))
            score = overlap + 0.25 * importance + 0.1 * rec
            if score > 0:
                scored.append((score, content, it))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [c for _, c, _ in scored[:k]]

        # 更新 lastUsedAt（只对命中的前 K 条）
        if top:
            now = _now_iso()
            items_map = { id(it): it for _, _, it in scored }
            # 直接按内容匹配更新
            for it in items:
                if it.get("content") in top:
                    it["lastUsedAt"] = now
            self._rewrite_all(items)

        return top


