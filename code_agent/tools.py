import os
import json
import re


def ensure_within_project(project_dir: str, file_path: str) -> str:
    if not os.path.isabs(file_path):
        raise ValueError("文件路径必须使用绝对路径，并且位于指定项目目录内。")
    abs_path = os.path.realpath(file_path)
    proj = os.path.realpath(project_dir)
    if abs_path != proj and not abs_path.startswith(proj + os.sep):
        raise ValueError(f"文件路径必须在指定项目目录内：{proj}，实际为：{abs_path}")
    return abs_path


def make_tools(project_dir: str):
    def _index_paths():
        base = os.path.join(project_dir, ".codeagent", "code_index")
        return {
            "files": os.path.join(base, "files.jsonl"),
            "symbols": os.path.join(base, "symbols.jsonl"),
            "chunks": os.path.join(base, "chunks.jsonl"),
            "stats": os.path.join(base, "stats.json"),
        }

    def _load_jsonl(path: str):
        items = []
        if not os.path.exists(path):
            return items
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
        return items

    def _tokenize(text: str):
        return re.findall(r"[\w\u4e00-\u9fff]+", (text or "").lower())

    def read_file(file_path: str):
        """用于读取文件内容（只允许读取指定项目目录内的绝对路径）"""
        abs_path = ensure_within_project(project_dir, file_path)
        with open(abs_path, "r", encoding="utf-8") as f:
            return f.read()

    def write_to_file(file_path: str, content: str):
        """将指定内容写入指定文件（只允许写入指定项目目录内的绝对路径）"""
        abs_path = ensure_within_project(project_dir, file_path)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content.replace("\\n", "\n"))
        return "写入成功"

    def run_terminal_command(command: str):
        """用于执行终端命令（在指定项目目录作为工作目录下执行）"""
        import subprocess
        run_result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=project_dir,
        )
        if run_result.returncode == 0:
            output = (run_result.stdout or "").strip()
            if not output:
                output = (run_result.stderr or "").strip() or "无输出"
            return output
        else:
            stdout = (run_result.stdout or "").strip()
            stderr = (run_result.stderr or "").strip()
            return f"命令执行失败\nstdout:\n{stdout}\n\nstderr:\n{stderr}"

    def index_stats():
        """读取代码索引统计信息。若不存在则返回简要提示。"""
        p = _index_paths()
        if os.path.exists(p["stats"]):
            with open(p["stats"], "r", encoding="utf-8") as f:
                return f.read()
        # 简单统计各文件是否存在
        exists = {k: os.path.exists(v) for k, v in p.items()}
        return json.dumps({"message": "索引不存在或未初始化", "exists": exists}, ensure_ascii=False)

    def files_search(query: str = "", lang: str | None = None, path_prefix: str | None = None, top_k: int = 50):
        """基于 files.jsonl 的文件级检索。

        参数：
        - query: 关键词（匹配路径/文件名）
        - lang: 语言过滤（如 python, typescript 等）
        - path_prefix: 限定相对路径前缀（如 src/）
        - top_k: 返回条数上限
        """
        p = _index_paths()
        items = _load_jsonl(p["files"])
        q = (query or "").lower()
        results = []
        for it in items:
            if lang and (it.get("language") or "").lower() != lang.lower():
                continue
            rel = it.get("relpath", "")
            if path_prefix and not rel.startswith(path_prefix):
                continue
            path = it.get("path", "")
            score = 0
            if q:
                score += (1 if q in rel.lower() else 0)
                score += (1 if q in os.path.basename(rel).lower() else 0)
            results.append((score, {
                "path": path,
                "relpath": rel,
                "language": it.get("language"),
                "lines": it.get("lines"),
                "size": it.get("size"),
            }))
        results.sort(key=lambda x: x[0], reverse=True)
        out = [r for _, r in results[: max(1, int(top_k))]]
        return json.dumps({"items": out}, ensure_ascii=False)

    def symbols_search(name: str, kind: str | None = None, lang: str | None = None, context_lines: int = 2, top_k: int = 50):
        """基于 symbols.jsonl 的符号检索（需安装 ctags）。

        参数：
        - name: 符号名（完整或子串）
        - kind: 符号类型（如 function/class/variable 等，取决于语言）
        - lang: 语言过滤
        - context_lines: 预览行数
        - top_k: 返回条数上限
        """
        p = _index_paths()
        items = _load_jsonl(p["symbols"])
        if not items:
            return json.dumps({"items": [], "message": "未发现符号索引（请安装 universal-ctags 并执行 --index-init）"}, ensure_ascii=False)
        q = (name or "").lower()
        results = []
        for it in items:
            nm = (it.get("name") or "").lower()
            if q and q not in nm:
                continue
            if kind and (it.get("kind") or "").lower() != kind.lower():
                continue
            if lang and (it.get("language") or "").lower() != lang.lower():
                continue
            # 读取预览
            path = ensure_within_project(project_dir, os.path.abspath(it.get("path", "")))
            line = int(it.get("line", 1))
            preview = ""
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                start = max(0, line - 1 - int(context_lines))
                end = min(len(lines), line - 1 + int(context_lines) + 1)
                preview = "".join(lines[start:end])[:300]
            except Exception:
                preview = ""
            results.append((len(nm), {
                "path": path,
                "line": line,
                "name": it.get("name"),
                "kind": it.get("kind"),
                "language": it.get("language"),
                "preview": preview,
            }))
        # 简单排序（更短的精确命中优先）
        results.sort(key=lambda x: x[0])
        out = [r for _, r in results[: max(1, int(top_k))]]
        return json.dumps({"items": out}, ensure_ascii=False)

    def chunks_search(query: str, lang: str | None = None, path_prefix: str | None = None, top_k: int = 20):
        """基于 chunks.jsonl 的块级检索。

        参数：
        - query: 关键词（与 identifiers/preview 匹配）
        - lang: 语言过滤
        - path_prefix: 限定相对路径前缀
        - top_k: 返回条数上限
        """
        p = _index_paths()
        items = _load_jsonl(p["chunks"])
        if not items:
            return json.dumps({"items": [], "message": "未发现块索引（请执行 --index-init 生成 chunks.jsonl）"}, ensure_ascii=False)
        q = (query or "").lower()
        q_tokens = set(_tokenize(query))
        results = []
        for it in items:
            if lang and (it.get("language") or "").lower() != lang.lower():
                continue
            rel = it.get("relpath") or os.path.relpath(it.get("path", ""), project_dir)
            if path_prefix and not rel.startswith(path_prefix):
                continue
            preview = it.get("preview", "")
            identifiers = it.get("identifiers", [])
            id_tokens = set(identifiers)
            overlap = len(q_tokens & id_tokens)
            score = 0.0
            score += 0.6 * overlap
            score += 0.4 * (1 if q and q in (preview or "").lower() else 0)
            if score > 0:
                results.append((score, {
                    "path": it.get("path"),
                    "relpath": rel,
                    "startLine": it.get("startLine"),
                    "endLine": it.get("endLine"),
                    "language": it.get("language"),
                    "preview": (preview or "")[:300],
                    "score": round(score, 3),
                }))
        results.sort(key=lambda x: x[0], reverse=True)
        out = [r for _, r in results[: max(1, int(top_k))]]
        return json.dumps({"items": out}, ensure_ascii=False)

    def mixed_search(query: str, top_k: int = 20):
        """混合检索：综合 symbols → chunks → files，返回融合结果。"""
        # symbols
        sym = json.loads(symbols_search(query, None, None, 1, max(5, int(top_k)//3)))
        # chunks
        chk = json.loads(chunks_search(query, None, None, max(5, int(top_k)//2)))
        # files
        fil = json.loads(files_search(query, None, None, max(5, int(top_k)//3)))
        merged = []
        seen = set()
        # 以 symbols 为主，其次 chunks，再 files
        for group, weight in ((sym, 1.0), (chk, 0.7), (fil, 0.5)):
            for it in group.get("items", []):
                key = (it.get("path"), it.get("startLine") or it.get("line"))
                if key in seen:
                    continue
                seen.add(key)
                it["source"] = "symbols" if weight == 1.0 else ("chunks" if weight == 0.7 else "files")
                merged.append((weight, it))
        merged.sort(key=lambda x: x[0], reverse=True)
        out = [r for _, r in merged[: max(1, int(top_k))]]
        return json.dumps({"items": out}, ensure_ascii=False)

    def endpoints_search(query: str = "", method: str | None = None, path_prefix: str | None = None, top_k: int = 20):
        """基于 endpoints.jsonl 的接口检索。

        参数：
        - query: 关键词（匹配 route/handler/preview）
        - method: GET/POST/PUT/DELETE…（大小写不敏感）
        - path_prefix: 只返回以该前缀开头的路由（如 /api/ 或 /v1/）
        - top_k: 返回条数上限
        """
        p = _index_paths()
        path = p.get("endpoints")
        items = _load_jsonl(path)
        if not items:
            return json.dumps({"items": [], "message": "未发现 endpoints 索引（请执行 --index-init 以生成 endpoints.jsonl）"}, ensure_ascii=False)
        q = (query or "").lower()
        results = []
        for it in items:
            rt = (it.get("route") or "").lower()
            hd = (it.get("handler") or "").lower()
            pv = (it.get("preview") or "").lower()
            m = (it.get("method") or "").lower()
            if method and m != method.lower():
                continue
            if path_prefix and not rt.startswith(path_prefix.lower()):
                continue
            score = 0
            if q:
                score += (2 if q in rt else 0)
                score += (1 if q in hd else 0)
                score += (1 if q in pv else 0)
            results.append((score, it))
        results.sort(key=lambda x: x[0], reverse=True)
        out = [it for _, it in results[: max(1, int(top_k))]]
        return json.dumps({"items": out}, ensure_ascii=False)

    return [
        read_file,
        write_to_file,
        run_terminal_command,
        index_stats,
        files_search,
        symbols_search,
        chunks_search,
        mixed_search,
        endpoints_search,
    ]


