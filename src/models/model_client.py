"""
DeepSeek 模型客户端配置模块。
通过 OpenAI 兼容接口连接 DeepSeek API。
"""

from autogen_ext.models.openai import OpenAIChatCompletionClient
from config.settings import settings


def create_model_client() -> OpenAIChatCompletionClient:
    """
    创建并返回 DeepSeek API 的模型客户端。

    Returns:
        OpenAIChatCompletionClient: 配置好的模型客户端实例
    """
    return OpenAIChatCompletionClient(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model_info=settings.model_info,
    )
