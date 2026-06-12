"""
开发人员 Agent — 负责领取 Issue、编码实现、创建 PR。
"""

import os
from src.agents.base_agent import create_agent
from src.models.model_client import create_model_client
from src.tools import github_tools, git_tools, file_tools

# 读取系统提示词
_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "prompts", "developer_system.md")
with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
    _SYSTEM_MESSAGE = f.read()

# 开发人员可用的工具集
_DEVELOPER_TOOLS = [
    # Issue 操作
    github_tools.get_issue,
    github_tools.list_issues,
    github_tools.comment_on_issue,
    # Git 操作
    git_tools.clone_repository,
    git_tools.create_branch,
    git_tools.git_commit,
    git_tools.git_push,
    git_tools.get_current_branch,
    git_tools.get_git_status,
    # GitHub PR 操作
    github_tools.create_pull_request,
    github_tools.get_pull_request,
    # 文件操作
    file_tools.read_file,
    file_tools.write_file,
    file_tools.delete_file,
    file_tools.list_files,
    # 命令执行
    file_tools.run_command,
]


def create_developer_agent():
    """
    创建开发人员 Agent。

    Returns:
        AssistantAgent: 配置好的开发人员 Agent
    """
    model_client = create_model_client()
    return create_agent(
        name="开发人员",
        model_client=model_client,
        system_message=_SYSTEM_MESSAGE,
        tools=_DEVELOPER_TOOLS,
        description="开发人员，负责领取 Issue、编码实现、创建 PR",
    )
