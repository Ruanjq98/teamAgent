"""
开发经理 Agent — 负责需求澄清、任务拆解、迭代评估和项目收尾。
"""

import os
from src.agents.base_agent import create_agent
from src.models.model_client import create_model_client
from src.tools import github_tools

# 读取系统提示词
_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "prompts", "manager_system.md")
with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
    _SYSTEM_MESSAGE = f.read()

# 开发经理可用的工具集
_MANAGER_TOOLS = [
    # Issue 操作
    github_tools.create_issue,
    github_tools.comment_on_issue,
    github_tools.close_issue,
    github_tools.get_issue,
    github_tools.list_issues,
    github_tools.add_labels_to_issue,
    github_tools.remove_labels_from_issue,
    github_tools.get_issue_comments,
    github_tools.get_issue_labels,
    # PR 操作
    github_tools.get_pull_request,
    github_tools.list_pull_requests,
    github_tools.submit_pr_review,
    github_tools.merge_pull_request,
]


def create_manager_agent():
    """
    创建开发经理 Agent。

    Returns:
        AssistantAgent: 配置好的开发经理 Agent
    """
    model_client = create_model_client()
    return create_agent(
        name="开发经理",
        model_client=model_client,
        system_message=_SYSTEM_MESSAGE,
        tools=_MANAGER_TOOLS,
        description="开发经理，负责需求澄清、任务拆解、迭代评估和项目收尾",
    )
