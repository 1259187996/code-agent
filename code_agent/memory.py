import os
import json
import re
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import numpy as np
try:
    import faiss  # type: ignore
except Exception:  # pragma: no cover
    faiss = None  # 允许在未安装时降级到关键词检索


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

    def __init__(self, project_dir: str, embed_model: str = "all-MiniLM-L6-v2"):
        self.project_dir = os.path.abspath(project_dir)
        self.store_path = os.path.join(self.project_dir, ".codeagent", "memory.jsonl")
        os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
        # 向量索引相关
        self.embed_model_name = embed_model
        safe_model = self.embed_model_name.replace('/', '_')
        self.index_dir = os.path.join(self.project_dir, ".codeagent", "index", safe_model)
        self.index_path = os.path.join(self.index_dir, "index.faiss")
        self.meta_path = os.path.join(self.index_dir, "meta.jsonl")
        os.makedirs(self.index_dir, exist_ok=True)
        self._index = None  # faiss.Index
        self._meta: List[Dict[str, Any]] = []
        self._model = None  # SentenceTransformer

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
        # 将新增内容增量写入向量索引
        try:
            self._vector_upsert(item.get("content", ""))
        except Exception:
            pass

    # ===== 向量索引：加载/保存 =====
    def _load_embed_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # lazy import
            self._model = SentenceTransformer(self.embed_model_name)
        return self._model

    def _load_index(self):
        if faiss is None:
            return None
        if self._index is not None:
            return self._index
        if os.path.exists(self.index_path) and os.path.exists(self.meta_path):
            try:
                self._index = faiss.read_index(self.index_path)
                self._meta = self._read_meta()
                return self._index
            except Exception:
                self._index = None
                self._meta = []
        # 初始化空索引（使用内积 + 归一化向量实现 cosine）
        self._index = faiss.IndexFlatIP(384)  # all-MiniLM-L6-v2 输出 384 维
        self._meta = []
        return self._index

    def _save_index(self):
        if faiss is None or self._index is None:
            return
        faiss.write_index(self._index, self.index_path)
        self._write_meta(self._meta)

    def _read_meta(self) -> List[Dict[str, Any]]:
        data: List[Dict[str, Any]] = []
        if not os.path.exists(self.meta_path):
            return data
        with open(self.meta_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data.append(json.loads(line))
                except Exception:
                    continue
        return data

    def _write_meta(self, data: List[Dict[str, Any]]):
        os.makedirs(self.index_dir, exist_ok=True)
        with open(self.meta_path, "w", encoding="utf-8") as f:
            for it in data:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")

    # ===== 向量编码与增量写入 =====
    def _encode_norm(self, texts: List[str]) -> np.ndarray:
        model = self._load_embed_model()
        vecs = np.asarray(model.encode(texts, normalize_embeddings=True), dtype=np.float32)
        return vecs

    def _vector_upsert(self, content: str):
        if not content or faiss is None:
            return
        index = self._load_index()
        if index is None:
            return
        # 近似去重：与现有向量相似度 > 0.88 则忽略
        if len(self._meta) > 0:
            q = self._encode_norm([content])
            D, I = index.search(q, min(5, len(self._meta)))
            if D is not None and float(np.max(D)) > 0.88:
                return
        v = self._encode_norm([content])
        index.add(v)
        self._meta.append({"content": content})
        self._save_index()

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

        # 构造 content -> item 映射，便于打分
        by_content: Dict[str, Dict[str, Any]] = { it.get("content", ""): it for it in items }

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

        # 1) 向量候选
        vector_candidates: List[str] = []
        vector_scores: Dict[str, float] = {}
        if faiss is not None and self._load_index() is not None and len(self._meta) > 0:
            try:
                qv = self._encode_norm([query])
                topn = min(20, len(self._meta))
                D, I = self._index.search(qv, topn)  # type: ignore[attr-defined]
                for i, score in zip(I[0].tolist(), D[0].tolist()):
                    if i < 0:
                        continue
                    c = self._meta[i].get("content", "")
                    if c:
                        vector_candidates.append(c)
                        vector_scores[c] = max(vector_scores.get(c, 0.0), float(score))
            except Exception:
                pass

        # 2) 关键词/规则候选
        scored = []  # (score, content)
        for it in items:
            content = it.get("content", "")
            tokens = set(_tokenize(content))
            overlap = len(q_tokens & tokens)
            importance = float(it.get("importance", 0.5))
            rec = recency_score(it.get("lastUsedAt", it.get("createdAt", _now_iso())))
            vec = vector_scores.get(content, 0.0)
            # 混合打分：0.6 向量 + 0.25 重要度 + 0.15 新近性 + 0.2 关键词
            score = 0.6 * vec + 0.25 * importance + 0.15 * rec + 0.2 * overlap
            if score > 0:
                scored.append((score, content))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [c for _, c in scored[:k]]

        # 更新 lastUsedAt（只对命中的前 K 条）
        if top:
            now = _now_iso()
            # 直接按内容匹配更新
            for it in items:
                if it.get("content") in top:
                    it["lastUsedAt"] = now
            self._rewrite_all(items)

        return top

    # ===== 全量重建索引 =====
    def reindex(self):
        if faiss is None:
            return "未安装 faiss-cpu，无法重建索引。"
        items = self._iter_items()
        contents = [it.get("content", "") for it in items if it.get("content")]
        if not contents:
            # 清空索引
            self._index = faiss.IndexFlatIP(384)
            self._meta = []
            self._save_index()
            return "索引已重置（无记忆条目）。"
        vecs = self._encode_norm(contents)
        self._index = faiss.IndexFlatIP(vecs.shape[1])
        self._index.add(vecs)
        self._meta = [ {"content": c} for c in contents ]
        self._save_index()
        return f"索引重建完成：{len(contents)} 条。"


