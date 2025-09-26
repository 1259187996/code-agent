import os
import click
from datetime import datetime, timezone

from .tools import make_tools
from .session import SessionStore
from .memory import MemoryStore
from .agent import ReActAgent


@click.command()
@click.option("--load", "load_session_id", type=str, default=None, help="加载指定的 session_id 继续会话")
@click.option("--resume-last", is_flag=True, help="恢复最近一次会话")
def chat(load_session_id: str | None, resume_last: bool):
    """启动会话模式（REPL）。

    - 以当前工作目录作为 project_directory 安全边界
    - 支持多轮独立任务；通过摘要实现跨轮上下文锚点
    - 退出：输入 /exit 或使用 Ctrl+C/Ctrl+D
    """
    project_dir = os.path.abspath(os.getcwd())

    # 选择会话：新建 / 加载指定 / 恢复最近
    session: SessionStore
    if load_session_id:
        session = SessionStore(project_dir, session_id=load_session_id)
        config_path = session.paths["config"]
        if not os.path.exists(config_path):
            session.init_config(model="deepseek-chat")
        mode_tip = f"加载会话：{session.session_id}"
    elif resume_last:
        sessions_root = os.path.join(project_dir, ".codeagent", "sessions")
        last_id = None
        if os.path.isdir(sessions_root):
            entries = [
                (name, os.path.getmtime(os.path.join(sessions_root, name)))
                for name in os.listdir(sessions_root)
                if os.path.isdir(os.path.join(sessions_root, name))
            ]
            if entries:
                entries.sort(key=lambda x: x[1], reverse=True)
                last_id = entries[0][name_index] if (name_index := 0) == 0 else entries[0][0]
        if last_id:
            session = SessionStore(project_dir, session_id=last_id)
            mode_tip = f"恢复最近会话：{session.session_id}"
        else:
            session = SessionStore(project_dir)
            session.init_config(model="deepseek-chat")
            mode_tip = f"新建会话：{session.session_id}"
    else:
        session = SessionStore(project_dir)
        session.init_config(model="deepseek-chat")
        mode_tip = f"新建会话：{session.session_id}"
    memory = MemoryStore(project_dir)

    tools = make_tools(project_dir)
    agent = ReActAgent(tools=tools, model="deepseek-chat", project_directory=project_dir, session=session, memory=memory)

    print("\n== CodeAgent 会话模式 ==")
    print(f"项目目录：{project_dir}")
    print(mode_tip)
    print("输入任务以开始，/exit 退出。\n")

    while True:
        try:
            task = input("任务> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            break

        if not task:
            continue

        if task.lower() in {"/exit", "/quit"}:
            print("已退出。")
            break

        final_answer = agent.run(task)
        print(f"\n\n✅ Final Answer：{final_answer}\n")


