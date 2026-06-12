"""
测试人员 Agent — 负责 PR 审查、代码测试、质量保障。
"""

import os
from src.agents.base_agent import create_agent
from src.models.model_client import create_model_client
from src.tools import github_tools, git_tools, file_tools

# 读取系统提示词
_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "prompts", "tester_system.md")
with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
    _SYSTEM_MESSAGE = f.read()

# 测试人员可用的工具集
_TESTER_TOOLS = [
    # Issue 操作
    github_tools.get_issue,
    github_tools.list_issues,
    github_tools.comment_on_issue,
    github_tools.create_issue,  # 创建 Bug Issue
    # Git 操作
    git_tools.clone_repository,
    git_tools.fetch_pr_branch,
    git_tools.get_current_branch,
    git_tools.get_git_status,
    # PR 操作
    github_tools.list_pull_requests,
    github_tools.get_pull_request,
    github_tools.submit_pr_review,
    # 文件操作
    file_tools.read_file,
    file_tools.list_files,
    # 命令执行
    file_tools.run_command,
]


def create_tester_agent():
    """
    创建测试人员 Agent。

    Returns:
        AssistantAgent: 配置好的测试人员 Agent
    """
    model_client = create_model_client()
    return create_agent(
        name="测试人员",
        model_client=model_client,
        system_message=_SYSTEM_MESSAGE,
        tools=_TESTER_TOOLS,
        description="测试人员，负责 PR 审查、代码测试、质量保障",
    )
