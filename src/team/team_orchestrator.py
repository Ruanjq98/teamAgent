"""
团队编排器 — 配置和管理 AutoGen Agent 团队。

使用 SelectorGroupChat 让 LLM 动态选择下一个发言的 Agent，
结合 RoundRobinGroupChat 的固定轮转作为备选。
"""

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
from autogen_agentchat.ui import Console

from src.agents.manager_agent import create_manager_agent
from src.agents.developer_agent import create_developer_agent
from src.agents.tester_agent import create_tester_agent
from config.settings import settings


class TeamOrchestrator:
    """
    Agent 团队编排器。

    负责创建、配置和运行三个角色的 Agent 团队。
    """

    def __init__(self):
        self.manager: None = None
        self.developer: None = None
        self.tester: None = None
        self.team: None = None

    def setup(self):
        """创建所有 Agent 实例并配置团队。"""
        # 每个 Agent 使用自己的模型客户端（不共享，避免 _model_client 覆盖问题）
        self.manager = create_manager_agent()
        self.developer = create_developer_agent()
        self.tester = create_tester_agent()

        # 终止条件: 任务完成信号 OR 达到最大消息数
        termination = (
            TextMentionTermination("任务完成")
            | MaxMessageTermination(max_messages=settings.max_messages_per_round)
        )

        # 使用 RoundRobinGroupChat — 固定轮转（不依赖模型选择发言者）
        self.team = RoundRobinGroupChat(
            participants=[self.manager, self.developer, self.tester],
            termination_condition=termination,
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
