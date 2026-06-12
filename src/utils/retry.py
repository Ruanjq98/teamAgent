"""
API 重试机制 — 指数退避重试装饰器。

处理场景:
- GitHub API 限流 (429)
- 网络超时 (5xx)
- 临时性故障
"""

import asyncio
import functools
import random
from typing import Type, Tuple, Callable
from loguru import logger


# 默认重试配置
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # 秒
DEFAULT_MAX_DELAY = 60.0   # 秒
RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def async_retry(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    retryable_exceptions: Tuple[Type[Exception], ...] = RETRYABLE_EXCEPTIONS,
):
    """
    异步函数的指数退避重试装饰器。

    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟秒数
        max_delay: 最大延迟秒数
        retryable_exceptions: 可重试的异常类型

    Example:
        @async_retry(max_retries=3, base_delay=1.0)
        async def call_api():
            ...
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    if attempt == max_retries:
                        logger.error(
                            f"{func.__name__} 重试 {max_retries} 次后仍然失败: {e}"
                        )
                        raise
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                    logger.warning(
                        f"{func.__name__} 第 {attempt + 1}/{max_retries} 次重试，"
                        f"等待 {delay:.1f}s，错误: {e}"
                    )
                    await asyncio.sleep(delay)

            raise last_exception  # type: ignore

        return wrapper
    return decorator


def sync_retry(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    retryable_exceptions: Tuple[Type[Exception], ...] = RETRYABLE_EXCEPTIONS,
):
    """
    同步函数的指数退避重试装饰器。

    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟秒数
        max_delay: 最大延迟秒数
        retryable_exceptions: 可重试的异常类型
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import time

            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    if attempt == max_retries:
                        logger.error(
                            f"{func.__name__} 重试 {max_retries} 次后仍然失败: {e}"
                        )
                        raise
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                    logger.warning(
                        f"{func.__name__} 第 {attempt + 1}/{max_retries} 次重试，"
                        f"等待 {delay:.1f}s，错误: {e}"
                    )
                    time.sleep(delay)

            raise last_exception  # type: ignore

        return wrapper
    return decorator


def retry_call(func: Callable, *args, max_retries: int = 3, **kwargs):
    """
    直接重试一个函数调用（非装饰器方式）。

    Args:
        func: 要重试的函数
        *args: 位置参数
        max_retries: 最大重试次数
        **kwargs: 关键字参数

    Returns:
        函数返回值

    Raises:
        最后一次重试的异常
    """
    import time

    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except RETRYABLE_EXCEPTIONS as e:
            last_exception = e
            if attempt == max_retries:
                raise
            delay = min(1.0 * (2 ** attempt) + random.uniform(0, 1), 60.0)
            logger.warning(f"重试 {attempt + 1}/{max_retries}，等待 {delay:.1f}s: {e}")
            time.sleep(delay)

    raise last_exception  # type: ignore
