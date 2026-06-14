"""
Agent 行为测试 — 测试 Agent 创建、系统提示词加载、工具绑定。
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


class TestAgentCreation:
    """Agent 创建测试。"""

    def test_base_agent_create(self):
        """测试通过基类创建 Agent。"""
        from src.agents.base_agent import create_agent
        from autogen_ext.models.openai import OpenAIChatCompletionClient

        mock_client = MagicMock()

        def dummy_tool(x: int) -> str:
            """Test tool."""
            return str(x)

        agent = create_agent(
            name="TestAgent",
            model_client=mock_client,
            system_message="You are a test agent.",
            tools=[dummy_tool],
            description="Test agent description",
        )

        assert agent.name == "TestAgent"
        assert agent._description == "Test agent description"

    def test_manager_agent_creation(self):
        """测试开发经理 Agent 创建。"""
        from src.agents.manager_agent import create_manager_agent, _MANAGER_TOOLS

        with patch("src.agents.manager_agent.create_model_client") as mock_model:
            mock_client = MagicMock()
            mock_model.return_value = mock_client
            agent = create_manager_agent()
            assert agent.name == "开发经理"
            assert len(_MANAGER_TOOLS) == 13

    def test_developer_agent_creation(self):
        """测试开发人员 Agent 创建。"""
        from src.agents.developer_agent import create_developer_agent, _DEVELOPER_TOOLS

        with patch("src.agents.developer_agent.create_model_client") as mock_model:
            mock_client = MagicMock()
            mock_model.return_value = mock_client
            agent = create_developer_agent()
            assert agent.name == "开发人员"
            assert len(_DEVELOPER_TOOLS) == 16
            assert "开发人员" in agent._description

    def test_tester_agent_creation(self):
        """测试测试人员 Agent 创建。"""
        from src.agents.tester_agent import create_tester_agent, _TESTER_TOOLS

        with patch("src.agents.tester_agent.create_model_client") as mock_model:
            mock_client = MagicMock()
            mock_model.return_value = mock_client
            agent = create_tester_agent()
            assert agent.name == "测试人员"
            assert len(_TESTER_TOOLS) == 14
            assert "测试人员" in agent._description

    def test_agent_has_proper_tools(self):
        """测试每个 Agent 拥有正确的工具集。"""
        from src.agents.manager_agent import _MANAGER_TOOLS
        from src.agents.developer_agent import _DEVELOPER_TOOLS
        from src.agents.tester_agent import _TESTER_TOOLS

        # Manager tools
        tool_names_mgr = [t.__name__ for t in _MANAGER_TOOLS]
        assert "create_issue" in tool_names_mgr
        assert "merge_pull_request" in tool_names_mgr
        assert "submit_pr_review" in tool_names_mgr

        # Developer tools
        tool_names_dev = [t.__name__ for t in _DEVELOPER_TOOLS]
        assert "write_file" in tool_names_dev
        assert "git_commit" in tool_names_dev
        assert "create_pull_request" in tool_names_dev
        assert "run_command" in tool_names_dev

        # Tester tools
        tool_names_tst = [t.__name__ for t in _TESTER_TOOLS]
        assert "read_file" in tool_names_tst
        assert "submit_pr_review" in tool_names_tst
        assert "run_command" in tool_names_tst
        # Tester should NOT have merge_pull_request
        assert "merge_pull_request" not in tool_names_tst


class TestSystemPrompts:
    """系统提示词测试。"""

    def test_manager_prompt_loaded(self):
        """测试开发经理提示词正确加载。"""
        prompt_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "prompts", "manager_system.md"
        )
        assert os.path.exists(prompt_path), f"Prompt file missing: {prompt_path}"

        with open(prompt_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "开发经理" in content
        assert "需求澄清" in content
        assert len(content) > 500

    def test_developer_prompt_loaded(self):
        """测试开发人员提示词正确加载。"""
        prompt_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "prompts", "developer_system.md"
        )
        assert os.path.exists(prompt_path), f"Prompt file missing: {prompt_path}"

        with open(prompt_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "开发人员" in content
        assert "clone_repository" in content
        assert len(content) > 400

    def test_tester_prompt_loaded(self):
        """测试测试人员提示词正确加载。"""
        prompt_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "prompts", "tester_system.md"
        )
        assert os.path.exists(prompt_path), f"Prompt file missing: {prompt_path}"

        with open(prompt_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "测试人员" in content
        assert "APPROVE" in content
        assert len(content) > 400


class TestModelClient:
    """模型客户端测试。"""

    def test_create_model_client(self):
        """测试模型客户端创建。"""
        from src.models.model_client import create_model_client

        client = create_model_client()
        assert client is not None
        assert client._model_info is not None

    def test_model_info_correct(self):
        """测试 model_info 配置正确。"""
        from config.settings import settings

        info = settings.model_info
        assert info["vision"] == False
        assert info["function_calling"] == True
        assert info["json_output"] == False
        assert info["family"] == "deepseek"
