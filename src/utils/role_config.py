"""
角色配置加载器 — 从 YAML/JSON 文件加载自定义角色配置。

P3.3: 支持通过配置文件自定义角色提示词、工具集和模型。
"""

import os
import yaml
from typing import Optional, Any
from loguru import logger

DEFAULT_CONFIG_PATH = "config/default_roles.yaml"


class RoleConfig:
    """单个角色的配置。"""

    def __init__(self, data: dict):
        self.name: str = data.get("name", "Unknown")
        self.description: str = data.get("description", "")
        self.model: str = data.get("model", "default")
        self.system_prompt_file: Optional[str] = data.get("system_prompt_file")
        self.tools: list[str] = data.get("tools", [])

    def load_system_prompt(self) -> str:
        """从文件加载系统提示词。"""
        if self.system_prompt_file and os.path.exists(self.system_prompt_file):
            with open(self.system_prompt_file, "r", encoding="utf-8") as f:
                return f.read()
        logger.warning(f"系统提示词文件不存在: {self.system_prompt_file}")
        return ""

    def get_tool_list(self) -> list[str]:
        """获取工具名称列表。"""
        return self.tools


class RolesConfig:
    """
    全局角色配置加载器。

    用法:
        config = RolesConfig.load("config/default_roles.yaml")
        manager = config.manager
        print(manager.name, manager.tools)
    """

    def __init__(self, data: dict):
        self.global_config: dict = data.get("global", {})
        self.manager = RoleConfig(data.get("manager", {}))
        self.developer = RoleConfig(data.get("developer", {}))
        self.tester = RoleConfig(data.get("tester", {}))

    @classmethod
    def load(cls, path: Optional[str] = None) -> "RolesConfig":
        """
        加载角色配置文件。

        Args:
            path: 配置文件路径。为 None 时使用默认路径。

        Returns:
            RolesConfig: 配置实例
        """
        path = path or DEFAULT_CONFIG_PATH

        if not os.path.exists(path):
            logger.warning(f"配置文件不存在: {path}，使用默认配置")
            return cls._default()

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        logger.info(f"角色配置已加载: {path}")
        return cls(data)

    @classmethod
    def _default(cls) -> "RolesConfig":
        """返回默认配置。"""
        return cls({
            "global": {"max_turns": 50, "max_iterations": 20},
            "manager": {"name": "开发经理"},
            "developer": {"name": "开发人员"},
            "tester": {"name": "测试人员"},
        })

    @property
    def max_iterations(self) -> int:
        return self.global_config.get("max_iterations", 20)

    @property
    def max_turns(self) -> int:
        return self.global_config.get("max_turns", 50)

    @property
    def termination_signal(self) -> str:
        return self.global_config.get("termination_signal", "任务完成")
