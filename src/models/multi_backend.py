"""
多模型后端支持 — 通过配置切换不同 LLM 供应商。

P3.4: 支持 DeepSeek / OpenAI / Ollama 等多种后端。
"""

from typing import Optional
from autogen_ext.models.openai import OpenAIChatCompletionClient
from config.settings import settings
from loguru import logger


class ModelBackend:
    """模型后端配置。"""

    DEEPSEEK = "deepseek"
    OPENAI = "openai"
    OLLAMA = "ollama"


# 默认 model_info 配置
MODEL_INFO_MAP = {
    ModelBackend.DEEPSEEK: {
        "vision": False,
        "function_calling": True,
        "json_output": False,
        "family": "deepseek",
    },
    ModelBackend.OPENAI: {
        "vision": True,
        "function_calling": True,
        "json_output": True,
        "family": "openai",
    },
    ModelBackend.OLLAMA: {
        "vision": False,
        "function_calling": True,
        "json_output": False,
        "family": "unknown",
    },
}


def create_client_for_backend(
    backend: str = ModelBackend.DEEPSEEK,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> OpenAIChatCompletionClient:
    """
    根据后端类型创建模型客户端。

    Args:
        backend: 后端类型 ("deepseek", "openai", "ollama")
        model: 模型名称 (为 None 时使用 settings 中的配置)
        api_key: API 密钥
        base_url: API 基础 URL

    Returns:
        OpenAIChatCompletionClient: 配置好的客户端
    """
    backend = backend.lower()

    if backend == ModelBackend.DEEPSEEK:
        model = model or settings.deepseek_model
        api_key = api_key or settings.deepseek_api_key
        base_url = base_url or settings.deepseek_base_url
    elif backend == ModelBackend.OPENAI:
        model = model or "gpt-4o"
        api_key = api_key or settings.deepseek_api_key
        base_url = base_url or "https://api.openai.com/v1"
    elif backend == ModelBackend.OLLAMA:
        model = model or "llama3"
        api_key = api_key or "ollama"
        base_url = base_url or "http://localhost:11434/v1"
    else:
        raise ValueError(f"不支持的后端: {backend}。可用: deepseek, openai, ollama")

    model_info = MODEL_INFO_MAP.get(backend, MODEL_INFO_MAP[ModelBackend.DEEPSEEK])

    logger.info(f"模型客户端: backend={backend}, model={model}, base_url={base_url}")

    return OpenAIChatCompletionClient(
        model=model,
        api_key=api_key,
        base_url=base_url,
        model_info=model_info,
    )


def list_available_backends() -> list[str]:
    """列出所有可用的后端。"""
    return [ModelBackend.DEEPSEEK, ModelBackend.OPENAI, ModelBackend.OLLAMA]
