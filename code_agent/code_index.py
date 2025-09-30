import os
import json
import subprocess
import re
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple


IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".DS_Store", "node_modules", ".venv", "venv",
    "dist", "build", "out", "__pycache__", ".idea", ".vscode", ".codeagent",
}

TEXT_EXTS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".go", ".rs",
    ".java", ".kt", ".swift", ".c", ".h", ".cpp", ".hpp", ".cs", ".rb",
    ".php", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".sh", ".bash",
    ".zsh", ".sql", ".csv", ".txt",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _detect_language(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    mapping = {
        ".py": "python", ".ts": "typescript", ".tsx": "typescript",
        ".js": "javascript", ".jsx": "javascript", ".go": "go",
        ".rs": "rust", ".java": "java", ".kt": "kotlin", ".swift": "swift",
        ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
        ".cs": "csharp", ".rb": "ruby", ".php": "php",
        ".yml": "yaml", ".yaml": "yaml", ".toml": "toml", ".ini": "ini",
        ".cfg": "ini", ".sh": "shell", ".bash": "shell", ".zsh": "shell",
        ".sql": "sql", ".json": "json", ".md": "markdown",
    }
    return mapping.get(ext, ext.lstrip("."))


class CodeIndex:
    """代码索引：文件清单 + 可选符号索引（ctags）。

    结果写入：
      - .codeagent/code_index/files.jsonl
      - .codeagent/code_index/symbols.jsonl（若安装了 universal-ctags）
      - .codeagent/code_index/stats.json
    """

    def __init__(self, project_dir: str):
        self.project_dir = os.path.abspath(project_dir)
        self.index_dir = os.path.join(self.project_dir, ".codeagent", "code_index")
        os.makedirs(self.index_dir, exist_ok=True)
        self.files_path = os.path.join(self.index_dir, "files.jsonl")
        self.symbols_path = os.path.join(self.index_dir, "symbols.jsonl")
        self.chunks_path = os.path.join(self.index_dir, "chunks.jsonl")
        self.endpoints_path = os.path.join(self.index_dir, "endpoints.jsonl")
        self.stats_path = os.path.join(self.index_dir, "stats.json")

    def init(self, scope: Optional[str] = None, max_size_mb: int = 10, chunk_lines: int = 300, chunk_overlap: int = 50) -> str:
        """首次构建索引（若存在将覆盖）。"""
        files = list(self._iter_files(scope=scope, max_size_mb=max_size_mb))
        self._write_files(files)
        sym_count = self._build_symbols(scope)
        chk_count = self._build_chunks(chunk_lines=chunk_lines, chunk_overlap=chunk_overlap)
        ep_count = self._build_endpoints(scope)
        self._write_stats(files_count=len(files), symbols_count=sym_count, chunks_count=chk_count, endpoints_count=ep_count)
        return f"索引完成：files={len(files)}, symbols={sym_count}, chunks={chk_count}, endpoints={ep_count}"

    def reindex(self, scope: Optional[str] = None, max_size_mb: int = 10, chunk_lines: int = 300, chunk_overlap: int = 50) -> str:
        """重建索引（覆盖）。"""
        return self.init(scope=scope, max_size_mb=max_size_mb, chunk_lines=chunk_lines, chunk_overlap=chunk_overlap)

    def stats(self) -> Dict[str, object]:
        if not os.path.exists(self.stats_path):
            return {"message": "索引不存在"}
        with open(self.stats_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ===== internals =====
    def _iter_files(self, scope: Optional[str], max_size_mb: int) -> Iterable[Dict[str, object]]:
        root = self.project_dir
        scope_prefix = os.path.join(root, scope) if scope else root
        scope_prefix = os.path.abspath(scope_prefix)
        for dirpath, dirnames, filenames in os.walk(scope_prefix):
            # 过滤忽略目录
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
            for name in filenames:
                path = os.path.abspath(os.path.join(dirpath, name))
                # 安全边界
                if not (path == root or path.startswith(root + os.sep)):
                    continue
                try:
                    st = os.stat(path)
                except Exception:
                    continue
                size_mb = st.st_size / (1024 * 1024)
                if size_mb > max_size_mb:
                    continue
                ext = os.path.splitext(name)[1].lower()
                is_text = ext in TEXT_EXTS
                lang = _detect_language(path) if is_text else "binary"
                line_count = None
                if is_text:
                    try:
                        with open(path, "r", encoding="utf-8", errors="ignore") as f:
                            line_count = sum(1 for _ in f)
                    except Exception:
                        line_count = None
                yield {
                    "path": path,
                    "relpath": os.path.relpath(path, root),
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "is_text": is_text,
                    "language": lang,
                    "lines": line_count,
                }

    def _write_files(self, items: List[Dict[str, object]]):
        with open(self.files_path, "w", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")

    def _build_symbols(self, scope: Optional[str]) -> int:
        # 尝试使用 universal-ctags 构建符号索引
        try:
            subprocess.run(["ctags", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except Exception:
            # 未安装则跳过
            try:
                if os.path.exists(self.symbols_path):
                    os.remove(self.symbols_path)
            except Exception:
                pass
            return 0

        target_dir = os.path.join(self.project_dir, scope) if scope else self.project_dir
        target_dir = os.path.abspath(target_dir)
        cmd = [
            "ctags", "-R", "-n",
            "--fields=+n",  # 包含行号
            "--output-format=json",
            "-f", "-",
            target_dir,
        ]
        count = 0
        with open(self.symbols_path, "w", encoding="utf-8") as out:
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                assert proc.stdout is not None
                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        # 仅保留真正的 tag 项（剔除非 tag 的事件）
                        if obj.get("_type") == "tag":
                            out.write(json.dumps({
                                "path": obj.get("path"),
                                "name": obj.get("name"),
                                "kind": obj.get("kind"),
                                "line": obj.get("line"),
                                "language": obj.get("language"),
                            }, ensure_ascii=False) + "\n")
                            count += 1
                    except Exception:
                        continue
                proc.wait(timeout=10)
            except Exception:
                return count
        return count

    def _write_stats(self, files_count: int, symbols_count: int, chunks_count: int, endpoints_count: int):
        data = {
            "project_dir": self.project_dir,
            "files": files_count,
            "symbols": symbols_count,
            "chunks": chunks_count,
            "endpoints": endpoints_count,
            "updated_at": _now_iso(),
        }
        with open(self.stats_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ===== 块级索引（基于行切分）=====
    def _build_chunks(self, chunk_lines: int = 300, chunk_overlap: int = 50) -> int:
        # 读取 files.jsonl，针对 is_text 的文件进行分块
        if not os.path.exists(self.files_path):
            return 0
        # 覆盖写
        count = 0
        with open(self.chunks_path, "w", encoding="utf-8") as out:
            with open(self.files_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        item = json.loads(line)
                    except Exception:
                        continue
                    if not item.get("is_text"):
                        continue
                    path = item.get("path")
                    if not path or not os.path.exists(path):
                        continue
                    try:
                        with open(path, "r", encoding="utf-8", errors="ignore") as rf:
                            lines = rf.readlines()
                    except Exception:
                        continue
                    n = len(lines)
                    if n == 0:
                        continue
                    step = max(1, chunk_lines - max(0, chunk_overlap))
                    start = 0
                    while start < n:
                        end = min(n, start + chunk_lines)
                        # 预览前 300 字符
                        snippet = "".join(lines[start:end])
                        preview = snippet[:300]
                        identifiers = self._extract_identifiers(snippet)
                        out.write(json.dumps({
                            "path": path,
                            "relpath": item.get("relpath"),
                            "startLine": start + 1,
                            "endLine": end,
                            "language": item.get("language"),
                            "preview": preview,
                            "identifiers": identifiers,
                        }, ensure_ascii=False) + "\n")
                        count += 1
                        if end == n:
                            break
                        start += step
        return count

    def _extract_identifiers(self, text: str) -> List[str]:
        # 提取可能的标识符/关键词，去除常见停用词，按频次截取前 20 个
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_\-]{2,}", text)
        lower = [t.lower() for t in tokens]
        stop = {
            "the","and","for","with","from","that","this","else","true","false","null","none",
            "return","class","def","func","function","var","let","const","import","export","public","private","protected",
            "if","elif","while","for","switch","case","break","continue","try","except","catch","finally","new","static",
        }
        freq: Dict[str,int] = {}
        for t in lower:
            if t in stop:
                continue
            freq[t] = freq.get(t, 0) + 1
        top = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:20]
        return [t for t,_ in top]

    # ===== 接口索引（Python/Java/Go 常见框架的简易模式匹配）=====
    def _build_endpoints(self, scope: Optional[str]) -> int:
        # 覆盖写
        count = 0
        try:
            with open(self.endpoints_path, "w", encoding="utf-8") as out:
                # 基于 files.jsonl 遍历文本文件
                if not os.path.exists(self.files_path):
                    return 0
                with open(self.files_path, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            item = json.loads(line)
                        except Exception:
                            continue
                        if not item.get("is_text"):
                            continue
                        path = item.get("path")
                        if not path or not os.path.exists(path):
                            continue
                        # 语言判断
                        lang = (item.get("language") or "").lower()
                        try:
                            with open(path, "r", encoding="utf-8", errors="ignore") as rf:
                                lines = rf.readlines()
                        except Exception:
                            continue
                        # 扫描行，匹配不同框架
                        for i, txt in enumerate(lines):
                            s = txt.strip()
                            # Python FastAPI/Starlette: @app.get("/x") / @router.post("/x")
                            m = re.match(r"@(?:[A-Za-z_][\w]*)\.(get|post|put|delete|patch|options|head)\(\s*['\"]([^'\"]+)['\"]", s, re.IGNORECASE)
                            if m and lang in {"python"}:
                                method = m.group(1).upper()
                                route = m.group(2)
                                handler = self._find_next_def(lines, i+1)
                                preview = self._preview(lines, i)
                                out.write(self._ep_record(path, i+1, method, route, "python-fastapi", handler, preview))
                                count += 1
                                continue
                            # Flask: @app.route("/x", methods=["GET","POST"]) 或单路径
                            m = re.match(r"@(?:[A-Za-z_][\w]*)\.route\(\s*['\"]([^'\"]+)['\"](.*)\)", s)
                            if m and lang in {"python"}:
                                route = m.group(1)
                                rest = m.group(2)
                                methods = re.findall(r"methods\s*=\s*\[([^\]]+)\]", rest)
                                method_list = ["ANY"]
                                if methods:
                                    method_list = [t.strip().strip('"\'"\'"') for t in re.split(r",", methods[0])]
                                    method_list = [mtd.upper() for mtd in method_list if mtd]
                                handler = self._find_next_def(lines, i+1)
                                preview = self._preview(lines, i)
                                for mtd in method_list:
                                    out.write(self._ep_record(path, i+1, mtd, route, "python-flask", handler, preview))
                                    count += 1
                                continue
                            # Django urls.py: path("/x", views.func) / re_path
                            if lang in {"python"} and ("path(" in s or "re_path(" in s):
                                dm = re.search(r"(?:path|re_path)\(\s*['\"]([^'\"]+)['\"]\s*,\s*([^)]+)\)", s)
                                if dm:
                                    route = dm.group(1)
                                    handler = dm.group(2).strip()
                                    preview = self._preview(lines, i)
                                    out.write(self._ep_record(path, i+1, "ANY", route, "python-django", handler, preview))
                                    count += 1
                                    continue
                            # Go gin/echo: r.GET("/x", handler)
                            gm = re.search(r"\.\s*(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\(\s*\"([^\"]+)\"\s*,\s*([A-Za-z0-9_\.]+)\s*\)", s)
                            if gm and lang in {"go"}:
                                method = gm.group(1).upper()
                                route = gm.group(2)
                                handler = gm.group(3)
                                preview = self._preview(lines, i)
                                out.write(self._ep_record(path, i+1, method, route, "go-gin", handler, preview))
                                count += 1
                                continue
                            # Java Spring: @GetMapping("/x") / @RequestMapping(value="/x", method=RequestMethod.GET)
                            if lang in {"java"}:
                                jm = re.search(r"@((?:Get|Post|Put|Delete|Patch)Mapping)\(\s*(?:value\s*=\s*)?\"([^\"]*)\"", s)
                                if jm:
                                    method = jm.group(1).replace("Mapping", "").upper()
                                    route = jm.group(2)
                                    handler = self._find_next_java_method(lines, i+1)
                                    preview = self._preview(lines, i)
                                    out.write(self._ep_record(path, i+1, method, route, "java-spring", handler, preview))
                                    count += 1
                                    continue
                                jm = re.search(r"@RequestMapping\(.*?value\s*=\s*\"([^\"]*)\".*?method\s*=\s*RequestMethod\.([A-Z]+).*?\)", s)
                                if jm:
                                    route = jm.group(1)
                                    method = jm.group(2).upper()
                                    handler = self._find_next_java_method(lines, i+1)
                                    preview = self._preview(lines, i)
                                    out.write(self._ep_record(path, i+1, method, route, "java-spring", handler, preview))
                                    count += 1
                                    continue
        except Exception:
            return count
        return count

    def _preview(self, lines: List[str], idx: int, context: int = 2) -> str:
        start = max(0, idx - context)
        end = min(len(lines), idx + context + 1)
        return "".join(lines[start:end])[:300]

    def _find_next_def(self, lines: List[str], start_idx: int) -> Optional[str]:
        for j in range(start_idx, min(start_idx + 10, len(lines))):
            m = re.match(r"def\s+([A-Za-z_][\w]*)\(", lines[j].strip())
            if m:
                return m.group(1)
        return None

    def _find_next_java_method(self, lines: List[str], start_idx: int) -> Optional[str]:
        for j in range(start_idx, min(start_idx + 20, len(lines))):
            m = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(.*\)\s*\{?\s*$", lines[j].strip())
            if m and (" class " not in lines[j]):
                return m.group(1)
        return None

    def _ep_record(self, path: str, line: int, method: str, route: str, framework: str, handler: Optional[str], preview: str) -> str:
        rec = {
            "path": path,
            "relpath": os.path.relpath(path, self.project_dir),
            "line": line,
            "method": method,
            "route": route,
            "framework": framework,
            "handler": handler,
            "preview": preview,
        }
        return json.dumps(rec, ensure_ascii=False) + "\n"


