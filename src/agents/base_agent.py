"""
Agent 基类 — 提供 Agent 创建和工具注册的通用逻辑。
"""

from typing import Optional
from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient


def create_agent(
    name: str,
    model_client: OpenAIChatCompletionClient,
    system_message: str,
    tools: Optional[list] = None,
    description: str = "",
) -> AssistantAgent:
    """
    创建一个配置好的 AssistantAgent 实例。

    Args:
        name: Agent 名称
        model_client: 模型客户端
        system_message: 系统提示词
        tools: 工具函数列表
        description: 简短描述（用于 SelectorGroupChat 选择发言者）

    Returns:
        AssistantAgent: 配置好的 Agent 实例
    """
    return AssistantAgent(
        name=name,
        model_client=model_client,
        system_message=system_message,
        tools=tools or [],
        description=description or name,
    )
