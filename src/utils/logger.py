"""
日志配置模块 — 基于 loguru 的结构化日志。

特性:
- 控制台彩色输出
- 文件日志自动轮转 (按天, 保留 7 天)
- 审计日志分离 (audit/)
- JSON 结构化日志 (可选, 用于日志分析)
- Agent 行为追踪专用 logger
"""

import sys
import os
from loguru import logger
from config.settings import settings


def setup_logger():
    """
    配置全局日志。

    三级日志体系:
    - 控制台: INFO+，彩色，简洁格式 — 供用户实时查看
    - 运行日志: DEBUG+，详细格式 — 供调试和问题排查
    - 审计日志: 通过 AuditTrail 类单独记录 — 供回溯和合规
    """
    # 移除默认 handler
    logger.remove()

    # 确保日志目录存在
    os.makedirs("logs", exist_ok=True)

    # 控制台输出 (INFO 及以上)
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<level>{message}</level>",
        level=settings.log_level,
        colorize=True,
        filter=lambda record: record["extra"].get("console", True),
    )

    # 运行日志 — 详细格式 (DEBUG 及以上)
    logger.add(
        "logs/team_agent_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | "
               "{level: <8} | "
               "{name}:{function}:{line} | "
               "{message}",
        level="DEBUG",
        rotation="1 day",
        retention="7 days",
        encoding="utf-8",
    )

    # JSON 结构化日志 — 供日志分析 (INFO 及以上)
    logger.add(
        "logs/structured_{time:YYYY-MM-DD}.jsonl",
        format="{message}",
        level="INFO",
        rotation="1 day",
        retention="3 days",
        encoding="utf-8",
        serialize=True,
    )

    # 错误日志 — 单独文件，仅 ERROR+
    logger.add(
        "logs/errors_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name}:{function}:{line} | {message}",
        level="ERROR",
        rotation="1 day",
        retention="30 days",
        encoding="utf-8",
    )

    return logger


def get_agent_logger(agent_name: str) -> logger:
    """
    为特定 Agent 创建带上下文的 logger。

    Args:
        agent_name: Agent 名称（开发经理/开发人员/测试人员）

    Returns:
        loguru.Logger: 绑定 Agent 上下文的 logger 实例

    Example:
        log = get_agent_logger("开发经理")
        log.info("开始需求分析")
    """
    return logger.bind(agent=agent_name, console=True)
