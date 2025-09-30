import os
import ast
import re
import inspect
from typing import List, Callable, Tuple

import platform
from openai import OpenAI
from dotenv import load_dotenv

from .session import SessionStore
from .memory import MemoryStore
from .prompt import build_system_prompt, react_system_prompt_template


class ReActAgent:
    def __init__(self, tools: List[Callable], model: str, project_directory: str, session: SessionStore | None = None, memory: MemoryStore | None = None):
        self.tools = { func.__name__: func for func in tools }
        self.model = model
        self.project_directory = project_directory
        self.session = session
        self.memory = memory
        self.client = OpenAI(
            base_url="https://api.deepseek.com",
            api_key=self.get_api_key(),
        )

    def run(self, user_input: str):
        # 基于用户输入检索记忆片段
        mem_snippets_text = ""
        if self.memory:
            try:
                top = self.memory.retrieve_topk(user_input, k=5)
                if top:
                    mem_snippets_text = "- " + "\n- ".join(top)
            except Exception:
                mem_snippets_text = ""

        system_content = self.render_system_prompt(mem_snippets_text)
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"<question>{user_input}</question>"}
        ]
        if self.session:
            self.session.append_message("system", system_content)
            self.session.append_message("user", f"<question>{user_input}</question>")

        while True:
            content = self.call_model(messages)
            if self.session:
                self.session.append_message("assistant", content)

            thought_match = re.search(r"<thought>(.*?)</thought>", content, re.DOTALL)
            if thought_match:
                print(f"\n\n💭 Thought: {thought_match.group(1)}")

            if "<final_answer>" in content:
                final_answer = re.search(r"<final_answer>(.*?)</final_answer>", content, re.DOTALL)
                if final_answer:
                    final_text = final_answer.group(1)
                else:
                    # 容错：模型可能缺少闭合标签或格式异常，取起始标签后的剩余内容
                    try:
                        final_text = content.split("<final_answer>", 1)[1].strip()
                    except Exception:
                        final_text = content.strip()
                if self.session:
                    try:
                        self.session.update_summary(user_input, final_text)
                    except Exception:
                        pass
                if self.memory:
                    try:
                        session_id = self.session.session_id if self.session else None
                        self.memory.add_from_turn(user_input, final_text, session_id=session_id)
                    except Exception:
                        pass
                return final_text

            action_match = re.search(r"<action>(.*?)</action>", content, re.DOTALL)
            if not action_match:
                raise RuntimeError("模型未输出 <action>")
            action = action_match.group(1)
            tool_name, args = self.parse_action(action)

            # 打印参数时可能包含非字符串（如 int），需安全转换为字符串
            try:
                args_str = ", ".join(str(a) for a in args)
            except Exception:
                args_str = ""
            print(f"\n\n🔧 Action: {tool_name}({args_str})")
            # 终端命令确认策略：支持 RUN_CMD_CONFIRM_MODE = always | never | only_delete（默认 always）
            if tool_name == "run_terminal_command":
                confirm_mode = self._get_run_command_confirm_mode()
                need_confirm = True
                if confirm_mode == "never":
                    need_confirm = False
                elif confirm_mode == "only_delete":
                    cmd_str = str(args[0]) if args else ""
                    need_confirm = self._is_potentially_destructive_command(cmd_str)
                # 执行确认
                should_continue = input(f"\n\n是否继续？（Y/N）") if need_confirm else "y"
            else:
                should_continue = "y"
            if should_continue.lower() != 'y':
                print("\n\n操作已取消。")
                return "操作被用户取消"

            try:
                observation = self.tools[tool_name](*args)
            except Exception as e:
                observation = f"工具执行错误：{str(e)}"
            print(f"\n\n🔍 Observation：{observation}")
            obs_msg = f"<observation>{observation}</observation>"
            messages.append({"role": "user", "content": obs_msg})
            if self.session:
                self.session.append_message("user", obs_msg)

    def get_tool_list(self) -> str:
        tool_descriptions = []
        for func in self.tools.values():
            name = func.__name__
            signature = str(inspect.signature(func))
            doc = inspect.getdoc(func)
            tool_descriptions.append(f"- {name}{signature}: {doc}")
        return "\n".join(tool_descriptions)

    def render_system_prompt(self, memory_snippets: str = "") -> str:
        tool_list = self.get_tool_list()
        file_list = ", ".join(
            os.path.abspath(os.path.join(self.project_directory, f))
            for f in os.listdir(self.project_directory)
        )
        summary = self.session.read_summary() if self.session else ""
        return build_system_prompt(
            react_system_prompt_template,
            self.get_operating_system_name(),
            tool_list,
            file_list,
            self.project_directory,
            summary,
            memory_snippets,
        )

    def get_api_key(self) -> str:
        """仅从环境变量读取 API Key，确保全局可用且行为一致。"""
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError(
                "未找到 DEEPSEEK_API_KEY 环境变量。请先在 shell 中执行：\n"
                "export DEEPSEEK_API_KEY=你的Key\n"
                "并确保在终端启动时自动加载（例如写入 ~/.zshrc）。"
            )
        return api_key

    def call_model(self, messages):
        print("\n\n正在请求模型，请稍等...")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
        content = response.choices[0].message.content
        messages.append({"role": "assistant", "content": content})
        return content

    def parse_action(self, code_str: str) -> Tuple[str, List[str]]:
        import ast
        match = re.match(r'(\w+)\((.*)\)', code_str, re.DOTALL)
        if not match:
            raise ValueError("Invalid function call syntax")
        func_name = match.group(1)
        args_str = match.group(2).strip()

        args: List[str] = []
        current_arg = ""
        in_string = False
        string_char = None
        i = 0
        paren_depth = 0

        while i < len(args_str):
            char = args_str[i]
            if not in_string:
                if char in ['"', "'"]:
                    in_string = True
                    string_char = char
                    current_arg += char
                elif char == '(':
                    paren_depth += 1
                    current_arg += char
                elif char == ')':
                    paren_depth -= 1
                    current_arg += char
                elif char == ',' and paren_depth == 0:
                    args.append(self._parse_single_arg(current_arg.strip()))
                    current_arg = ""
                else:
                    current_arg += char
            else:
                current_arg += char
                if char == string_char and (i == 0 or args_str[i-1] != '\\'):
                    in_string = False
                    string_char = None
            i += 1

        if current_arg.strip():
            args.append(self._parse_single_arg(current_arg.strip()))
        return func_name, args

    def _parse_single_arg(self, arg_str: str):
        arg_str = arg_str.strip()
        if (arg_str.startswith('"') and arg_str.endswith('"')) or \
           (arg_str.startswith("'") and arg_str.endswith("'")):
            inner_str = arg_str[1:-1]
            inner_str = inner_str.replace('\"', '"').replace("\\'", "'")
            inner_str = inner_str.replace('\\n', '\n').replace('\\t', '\t')
            inner_str = inner_str.replace('\\r', '\r').replace('\\\\', '\\')
            return inner_str
        try:
            return ast.literal_eval(arg_str)
        except (SyntaxError, ValueError):
            return arg_str

    def get_operating_system_name(self):
        os_map = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}
        return os_map.get(platform.system(), "Unknown")

    # ===== run_terminal_command 确认策略 =====
    def _get_run_command_confirm_mode(self) -> str:
        """从项目 .env 或环境变量读取确认策略。

        可选值："always"（默认）、"never"、"only_delete"。
        读取顺序：项目 .env -> 环境变量；均无时返回默认值。
        """
        # 先尝试从项目 .env 加载（不覆盖已有环境变量）
        try:
            dotenv_path = os.path.join(self.project_directory, ".env")
            if os.path.isfile(dotenv_path):
                load_dotenv(dotenv_path, override=False)
        except Exception:
            pass
        val = os.getenv("RUN_CMD_CONFIRM_MODE") or os.getenv("CODEAGENT_RUN_CONFIRM") or "always"
        val = (val or "").strip().lower()
        return val if val in {"always", "never", "only_delete"} else "always"

    def _is_potentially_destructive_command(self, command: str) -> bool:
        """粗略判断命令是否具有破坏性（删除/覆写/重置类）。"""
        if not command:
            return True
        cmd = command.strip().lower()
        dangerous_patterns = [
            r"(^|[;&|\s])rm\b",
            r"(^|[;&|\s])rmdir\b",
            r"(^|[;&|\s])del\b",
            r"(^|[;&|\s])mkfs\b",
            r"git\s+reset\s+--hard",
            r"git\s+clean\s+-fdx",
        ]
        for pat in dangerous_patterns:
            if re.search(pat, cmd):
                return True
        return False


