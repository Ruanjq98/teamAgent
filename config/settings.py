"""
全局配置加载模块。
从 .env 文件读取环境变量，提供统一的配置访问接口。
"""

import os
from dotenv import load_dotenv

# 自动加载项目根目录的 .env 文件
load_dotenv()


class Settings:
    """全局配置单例。"""

    # ========== DeepSeek API ==========
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/anthropic")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # ========== GitHub 配置 ==========
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    github_repo_owner: str = os.getenv("GITHUB_REPO_OWNER", "")
    github_repo_name: str = os.getenv("GITHUB_REPO_NAME", "")
    github_verify_ssl: bool = os.getenv("GITHUB_VERIFY_SSL", "true").lower() == "true"

    @property
    def github_repo_full(self) -> str:
        """返回 owner/repo 格式的仓库全名。"""
        return f"{self.github_repo_owner}/{self.github_repo_name}"

    # ========== 工作流配置 ==========
    max_iterations: int = int(os.getenv("MAX_ITERATIONS", "20"))
    max_messages_per_round: int = int(os.getenv("MAX_MESSAGES_PER_ROUND", "50"))

    # ========== 需求澄清轮询 ==========
    clarification_poll_interval: int = int(os.getenv("CLARIFICATION_POLL_INTERVAL", "60"))
    clarification_reminder_hours: int = int(os.getenv("CLARIFICATION_REMINDER_HOURS", "48"))
    clarification_suspend_days: int = int(os.getenv("CLARIFICATION_SUSPEND_DAYS", "7"))
    clarification_max_polls: int = int(os.getenv("CLARIFICATION_MAX_POLLS", "0"))

    # ========== 日志 ==========
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    # ========== 工作目录 ==========
    @property
    def workspace_dir(self) -> str:
        """返回 Agent 的本地工作目录（用于克隆仓库）。"""
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".workspace")

    # ========== DeepSeek model_info ==========
    @property
    def model_info(self) -> dict:
        """返回 AutoGen 所需的 model_info 字典。"""
        return {
            "vision": False,
            "function_calling": True,
            "json_output": False,
            "family": "deepseek",
        }


# 全局单例
settings = Settings()
