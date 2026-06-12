"""
回退与超时控制模块。

提供:
- 操作级别的超时保护
- 技术方案不可行时的回退机制
- 需求澄清超时处理
- 迭代计数和自动终止
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Callable
from loguru import logger

from config.settings import settings


class TimeoutGuard:
    """
    超时保护器 — 为异步操作提供超时控制。
    """

    def __init__(self, timeout_seconds: float = 60):
        self.timeout = timeout_seconds
        self.start_time: Optional[datetime] = None

    async def run_with_timeout(self, coro, error_message: str = "操作超时"):
        """
        为协程添加超时保护。

        Args:
            coro: 要执行的协程
            error_message: 超时时的错误消息

        Returns:
            协程的返回值

        Raises:
            TimeoutError: 超时
        """
        self.start_time = datetime.now()
        try:
            result = await asyncio.wait_for(coro, timeout=self.timeout)
            elapsed = (datetime.now() - self.start_time).total_seconds()
            logger.debug(f"操作完成，耗时 {elapsed:.1f}s (超时限制 {self.timeout}s)")
            return result
        except asyncio.TimeoutError:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            logger.error(f"{error_message} ({elapsed:.1f}s > {self.timeout}s)")
            raise TimeoutError(f"{error_message} (超时: {self.timeout}s)")

    @property
    def elapsed(self) -> float:
        """已用时（秒）。"""
        if self.start_time is None:
            return 0
        return (datetime.now() - self.start_time).total_seconds()


class RollbackManager:
    """
    回退管理器 — 跟踪可回退的操作并在需要时执行回退。

    支持:
    - 操作前注册回退函数
    - 失败时自动执行已注册的回退
    - 成功时清除回退栈
    """

    def __init__(self):
        self._rollback_stack: list[tuple[str, Callable]] = []

    def register(self, name: str, rollback_fn: Callable):
        """
        注册一个回退操作。

        Args:
            name: 回退操作名称
            rollback_fn: 异步或同步的回退函数
        """
        self._rollback_stack.append((name, rollback_fn))
        logger.debug(f"注册回退: {name} (栈深度: {len(self._rollback_stack)})")

    async def rollback_all(self) -> list[str]:
        """
        按注册的反序执行所有回退操作。

        Returns:
            成功回退的操作名称列表
        """
        rolled_back = []
        while self._rollback_stack:
            name, fn = self._rollback_stack.pop()
            try:
                logger.warning(f"执行回退: {name}")
                if asyncio.iscoroutinefunction(fn):
                    await fn()
                else:
                    fn()
                rolled_back.append(name)
                logger.info(f"回退成功: {name}")
            except Exception as e:
                logger.error(f"回退失败: {name} — {e}")
        return rolled_back

    def clear(self):
        """清除所有已注册的回退（操作成功时调用）。"""
        count = len(self._rollback_stack)
        self._rollback_stack.clear()
        if count > 0:
            logger.debug(f"已清除 {count} 个回退注册")

    @property
    def pending_count(self) -> int:
        return len(self._rollback_stack)


class IterationController:
    """
    迭代控制器 — 管理开发循环的状态和边界。

    职责:
    - 跟踪迭代计数
    - 检测是否达到最大迭代次数
    - 记录每轮迭代的结果
    - 强制输出需求完成度报告（每 5 轮）
    """

    def __init__(self, max_iterations: int = 20):
        self.max_iterations = max_iterations
        self.current_iteration = 0
        self.iteration_history: list[dict] = []
        self.start_time = datetime.now()

    def start_new_iteration(self) -> int:
        """开始新一轮迭代，返回轮次号。"""
        self.current_iteration += 1
        self.iteration_history.append({
            "iteration": self.current_iteration,
            "start_time": datetime.now().isoformat(),
            "status": "started",
        })
        return self.current_iteration

    def complete_iteration(self, result: dict):
        """标记当前迭代完成并记录结果。"""
        if self.iteration_history:
            self.iteration_history[-1].update({
                "end_time": datetime.now().isoformat(),
                "status": "completed",
                "result": result,
            })

    def should_force_report(self) -> bool:
        """是否应该强制输出进度报告（每 5 轮）。"""
        return self.current_iteration > 0 and self.current_iteration % 5 == 0

    def should_terminate(self) -> bool:
        """是否应该强制终止。"""
        return self.current_iteration >= self.max_iterations

    def is_excessive_review_cycle(self, pr_number: int, review_count: int) -> bool:
        """
        检测某个 PR 是否陷入过度审查循环。

        Args:
            pr_number: PR 编号
            review_count: 该 PR 的 Review 次数

        Returns:
            是否超过 3 次 Review（需要人工介入）
        """
        if review_count > 3:
            logger.warning(
                f"PR #{pr_number} 已收到 {review_count} 次 Review，"
                f"超过 3 次限制，建议开发经理介入决策"
            )
            return True
        return False

    def summary(self) -> dict:
        """返回迭代摘要。"""
        elapsed = datetime.now() - self.start_time
        return {
            "total_iterations": self.current_iteration,
            "max_iterations": self.max_iterations,
            "elapsed": str(elapsed),
            "history": [
                {"iter": h["iteration"], "status": h["status"]}
                for h in self.iteration_history
            ],
        }


class ClarificationTimeout:
    """
    需求澄清超时处理。

    规则:
    - 48 小时内用户未回复 → 发送一次提醒
    - 7 天未回复 → 暂停项目
    """

    REMINDER_AFTER = timedelta(hours=48)
    SUSPEND_AFTER = timedelta(days=7)

    def __init__(self, issue_number: int):
        self.issue_number = issue_number
        self.last_user_reply: Optional[datetime] = None
        self.reminder_sent = False
        self.suspended = False

    def record_user_reply(self):
        """记录用户的回复时间。"""
        self.last_user_reply = datetime.now()
        self.reminder_sent = False
        self.suspended = False

    def check_timeout(self) -> dict:
        """
        检查是否触发超时规则。

        Returns:
            dict: {
                "should_remind": bool,
                "should_suspend": bool,
                "inactive_duration": str,
            }
        """
        if self.last_user_reply is None:
            return {"should_remind": False, "should_suspend": False, "inactive_duration": "N/A"}

        inactive = datetime.now() - self.last_user_reply

        result = {
            "should_remind": False,
            "should_suspend": False,
            "inactive_duration": str(inactive),
        }

        if inactive >= self.SUSPEND_AFTER and not self.suspended:
            result["should_suspend"] = True
            self.suspended = True
        elif inactive >= self.REMINDER_AFTER and not self.reminder_sent:
            result["should_remind"] = True
            self.reminder_sent = True

        return result
