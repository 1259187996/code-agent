import os


def ensure_within_project(project_dir: str, file_path: str) -> str:
    if not os.path.isabs(file_path):
        raise ValueError("文件路径必须使用绝对路径，并且位于指定项目目录内。")
    abs_path = os.path.realpath(file_path)
    proj = os.path.realpath(project_dir)
    if abs_path != proj and not abs_path.startswith(proj + os.sep):
        raise ValueError(f"文件路径必须在指定项目目录内：{proj}，实际为：{abs_path}")
    return abs_path


def make_tools(project_dir: str):
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

    return [read_file, write_to_file, run_terminal_command]


