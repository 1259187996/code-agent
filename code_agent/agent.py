import os
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
                final_text = final_answer.group(1)
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

            print(f"\n\n🔧 Action: {tool_name}({', '.join(args)})")
            should_continue = input(f"\n\n是否继续？（Y/N）") if tool_name == "run_terminal_command" else "y"
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
        # 1) 直接读取环境变量
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if api_key:
            return api_key

        # 2) 尝试按优先级加载多个 .env 位置（不覆盖已有环境变量）
        candidate_env_paths = []
        try:
            if self.project_directory:
                candidate_env_paths.append(os.path.join(self.project_directory, ".env"))
        except Exception:
            pass
        candidate_env_paths.extend([
            os.path.join(os.getcwd(), ".env"),
            os.path.expanduser("~/.codeagent/.env"),
            os.path.expanduser("~/.config/codeagent/.env"),
        ])

        for p in candidate_env_paths:
            if p and os.path.isfile(p):
                load_dotenv(p, override=False)
                api_key = os.getenv("DEEPSEEK_API_KEY")
                if api_key:
                    return api_key

        # 3) 最后再尝试默认搜索（当前工作目录向上）
        load_dotenv()
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if api_key:
            return api_key

        raise ValueError(
            "未找到 DEEPSEEK_API_KEY。请通过以下任一方式配置：\n"
            "1) 在 shell 中导出：export DEEPSEEK_API_KEY=...\n"
            "2) 在当前项目或全局路径创建 .env：\n"
            "   - ./ .env\n"
            "   - ~/.codeagent/.env\n"
            "   - ~/.config/codeagent/.env\n"
            "   文件内容：DEEPSEEK_API_KEY=你的Key"
        )

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


