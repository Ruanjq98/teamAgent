"""
团队编排器 — 配置和管理 AutoGen Agent 团队。

使用 SelectorGroupChat 让 LLM 动态选择下一个发言的 Agent，
结合 RoundRobinGroupChat 的固定轮转作为备选。
"""

import asyncio
from typing import Optional
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import SelectorGroupChat, RoundRobinGroupChat
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
from autogen_agentchat.ui import Console

from src.agents.manager_agent import create_manager_agent
from src.agents.developer_agent import create_developer_agent
from src.agents.tester_agent import create_tester_agent
from src.models.model_client import create_model_client
from config.settings import settings


class TeamOrchestrator:
    """
    Agent 团队编排器。

    负责创建、配置和运行三个角色的 Agent 团队。
    """

    def __init__(self):
        self.manager: Optional[AssistantAgent] = None
        self.developer: Optional[AssistantAgent] = None
        self.tester: Optional[AssistantAgent] = None
        self.team: Optional[SelectorGroupChat] = None

    def setup(self):
        """创建所有 Agent 实例并配置团队。"""
        # 三个 Agent 共用一个模型客户端
        model_client = create_model_client()

        self.manager = create_manager_agent()
        self.manager._model_client = model_client

        self.developer = create_developer_agent()
        self.developer._model_client = model_client

        self.tester = create_tester_agent()
        self.tester._model_client = model_client

        # 终止条件: 任务完成信号 OR 达到最大消息数
        termination = (
            TextMentionTermination("任务完成")
            | MaxMessageTermination(max_messages=settings.max_messages_per_round)
        )

        # 使用 SelectorGroupChat — LLM 动态决定下一个发言的 Agent
        self.team = SelectorGroupChat(
            participants=[self.manager, self.developer, self.tester],
            model_client=model_client,
            termination_condition=termination,
            allow_repeated_speaker=False,
            max_turns=settings.max_messages_per_round,
        )

        return self

    async def run_iteration(self, task: str) -> str:
        """
        运行一次团队协作迭代。

        Args:
            task: 本轮的任务描述（会被注入到团队对话中）

        Returns:
            str: 本轮对话的摘要结果
        """
        if not self.team:
            raise RuntimeError("团队未初始化，请先调用 setup()")

        result = await Console(self.team.run_stream(task=task))
        return result

    async def run_with_callback(self, task: str, callback=None):
        """
        运行团队协作，并支持每轮消息的回调。

        Args:
            task: 任务描述
            callback: 每收到一条消息时调用的回调函数 (async callable)

        Returns:
            团队运行结果
        """
        if not self.team:
            raise RuntimeError("团队未初始化，请先调用 setup()")

        result = await self.team.run(task=task)
        return result


def create_orchestrator() -> TeamOrchestrator:
    """工厂函数：创建并初始化团队编排器。"""
    return TeamOrchestrator().setup()
