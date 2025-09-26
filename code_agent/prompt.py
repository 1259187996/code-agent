from prompt_template import react_system_prompt_template


def build_system_prompt(base_template: str, operating_system: str, tool_list: str, file_list: str, project_directory: str, session_summary: str, memory_snippets: str = "") -> str:
    from string import Template
    base = Template(base_template).substitute(
        operating_system=operating_system,
        tool_list=tool_list,
        file_list=file_list,
        project_directory=project_directory,
    )
    prefix_parts = []
    if session_summary:
        prefix_parts.append(f"会话摘要（仅供参考）：\n{session_summary}")
    if memory_snippets:
        prefix_parts.append(f"记忆提要：\n{memory_snippets}")
    if prefix_parts:
        return "\n\n⸻\n".join(prefix_parts) + "\n\n⸻\n" + base
    return base


__all__ = ["react_system_prompt_template", "build_system_prompt"]


