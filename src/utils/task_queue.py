"""
任务队列与并发控制 — 支持多项目并行执行。

P3.1: 使用 asyncio.Semaphore 控制并发数，每个任务在独立的管道实例中运行。
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Callable, Awaitable
from loguru import logger


@dataclass
class TaskItem:
    """任务队列中的单个任务。"""
    task_id: str
    requirement: str
    status: str = "queued"  # queued → running → completed/failed
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[dict] = None
    error: Optional[str] = None


class TaskQueue:
    """
    异步任务队列。

    特性:
    - 最大并发数控制 (semaphore)
    - 任务状态跟踪
    - 支持结果回调
    - 优雅关闭
    """

    def __init__(self, max_concurrency: int = 3):
        """
        Args:
            max_concurrency: 最大并发任务数
        """
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.tasks: dict[str, TaskItem] = {}
        self._running: set[str] = set()
        self._on_complete: Optional[Callable[[TaskItem], Awaitable[None]]] = None

    def on_complete(self, callback: Callable[[TaskItem], Awaitable[None]]):
        """注册任务完成回调。"""
        self._on_complete = callback

    def add_task(self, requirement: str, task_id: Optional[str] = None) -> str:
        """
        添加任务到队列。

        Args:
            requirement: 项目需求描述
            task_id: 任务 ID（为 None 时自动生成）

        Returns:
            str: 任务 ID
        """
        if task_id is None:
            task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.tasks)}"

        self.tasks[task_id] = TaskItem(
            task_id=task_id,
            requirement=requirement,
        )
        logger.info(f"任务 {task_id} 已加入队列: {requirement[:80]}...")
        return task_id

    async def run_all(self) -> list[dict]:
        """
        并发运行所有排队的任务。

        Returns:
            list[dict]: 所有任务的执行结果
        """
        pending = [tid for tid, t in self.tasks.items() if t.status == "queued"]
        if not pending:
            return []

        logger.info(f"开始执行 {len(pending)} 个任务 (最大并发: {self.semaphore._value})")

        coros = [self._run_single(tid) for tid in pending]
        results = await asyncio.gather(*coros, return_exceptions=True)

        summaries = []
        for tid, result in zip(pending, results):
            if isinstance(result, Exception):
                self.tasks[tid].status = "failed"
                self.tasks[tid].error = str(result)
                summaries.append({"task_id": tid, "status": "failed", "error": str(result)})
            else:
                summaries.append({"task_id": tid, "status": "completed", "result": result})

        return summaries

    async def _run_single(self, task_id: str):
        """运行单个任务（带并发控制）。"""
        task = self.tasks[task_id]
        task.status = "running"
        task.started_at = datetime.now()
        self._running.add(task_id)

        async with self.semaphore:
            try:
                from workflows.pipeline import WorkflowPipeline

                pipeline = WorkflowPipeline()
                result = await pipeline.run(task.requirement)

                task.status = "completed"
                task.result = result
                task.completed_at = datetime.now()

                if self._on_complete:
                    await self._on_complete(task)

                logger.info(f"任务 {task_id} 完成")
                return result

            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                task.completed_at = datetime.now()
                logger.error(f"任务 {task_id} 失败: {e}")
                raise
            finally:
                self._running.discard(task_id)

    def get_status(self, task_id: Optional[str] = None) -> dict:
        """
        获取任务状态。

        Args:
            task_id: 任务 ID。为 None 时返回所有任务状态。

        Returns:
            dict: 任务状态信息
        """
        if task_id:
            task = self.tasks.get(task_id)
            if not task:
                return {"error": f"任务 {task_id} 不存在"}
            return {
                "task_id": task.task_id,
                "status": task.status,
                "requirement": task.requirement[:200],
                "created_at": task.created_at.isoformat(),
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            }

        return {
            "total": len(self.tasks),
            "queued": sum(1 for t in self.tasks.values() if t.status == "queued"),
            "running": sum(1 for t in self.tasks.values() if t.status == "running"),
            "completed": sum(1 for t in self.tasks.values() if t.status == "completed"),
            "failed": sum(1 for t in self.tasks.values() if t.status == "failed"),
            "tasks": [
                {
                    "task_id": t.task_id,
                    "status": t.status,
                    "requirement": t.requirement[:100],
                }
                for t in self.tasks.values()
            ],
        }
