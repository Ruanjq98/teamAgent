"""
审计追踪模块 — 记录所有关键操作，便于回溯和调试。

记录维度:
- Agent 行为（谁在什么时候做了什么）
- 工具调用（调用了哪个工具、参数、结果）
- 工作流状态变化（阶段转换）
- 异常事件（错误、重试、回退）
"""

import json
import os
import time
from datetime import datetime
from typing import Any, Optional
from loguru import logger


# 审计日志目录
AUDIT_DIR = "logs/audit"


def _ensure_audit_dir():
    """确保审计日志目录存在。"""
    os.makedirs(AUDIT_DIR, exist_ok=True)


class AuditTrail:
    """
    审计追踪器 — 记录完整的项目执行轨迹。
    """

    def __init__(self, project_id: str):
        _ensure_audit_dir()
        self.project_id = project_id
        self.start_time = datetime.now()
        self.events: list[dict] = []
        self.tool_calls: list[dict] = []
        self.errors: list[dict] = []

    def log_event(self, event_type: str, agent: str, message: str, details: Optional[dict] = None):
        """
        记录通用事件。

        Args:
            event_type: 事件类型 (phase_start, phase_end, decision, iteration_start, etc.)
            agent: 触发事件的 Agent 名称
            message: 事件描述
            details: 额外详情
        """
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "agent": agent,
            "message": message,
            "details": details or {},
        }
        self.events.append(event)
        logger.debug(f"[AUDIT] {event_type} | {agent} | {message}")

    def log_tool_call(self, agent: str, tool_name: str, args: dict, result: str, duration_ms: float):
        """
        记录工具调用。

        Args:
            agent: 调用工具的 Agent
            tool_name: 工具名称
            args: 调用参数
            result: 返回结果（截断）
            duration_ms: 耗时（毫秒）
        """
        call = {
            "timestamp": datetime.now().isoformat(),
            "agent": agent,
            "tool": tool_name,
            "args": self._sanitize_args(args),
            "result_preview": result[:500],
            "duration_ms": round(duration_ms, 2),
        }
        self.tool_calls.append(call)
        logger.debug(f"[TOOL] {agent} -> {tool_name} ({duration_ms:.0f}ms)")

    def log_error(self, agent: str, error_type: str, message: str, stack_trace: Optional[str] = None):
        """
        记录错误事件。

        Args:
            agent: 遇到错误的 Agent
            error_type: 错误类型
            message: 错误描述
            stack_trace: 堆栈跟踪
        """
        error = {
            "timestamp": datetime.now().isoformat(),
            "agent": agent,
            "type": error_type,
            "message": message,
            "stack_trace": stack_trace,
        }
        self.errors.append(error)
        logger.error(f"[ERROR] {agent} | {error_type}: {message}")

    def log_phase_change(self, from_phase: str, to_phase: str, reason: str):
        """
        记录工作流阶段变化。

        Args:
            from_phase: 来源阶段
            to_phase: 目标阶段
            reason: 变化原因
        """
        self.log_event(
            "phase_change",
            "Pipeline",
            f"{from_phase} → {to_phase}",
            {"from": from_phase, "to": to_phase, "reason": reason},
        )

    def log_iteration(self, iteration: int, action: str, details: Optional[dict] = None):
        """记录迭代事件。"""
        self.log_event(
            "iteration",
            "Pipeline",
            f"第 {iteration} 轮迭代: {action}",
            {"iteration": iteration, "action": action, **(details or {})},
        )

    def flush(self):
        """将审计日志写入磁盘。"""
        _ensure_audit_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(AUDIT_DIR, f"audit_{self.project_id}_{timestamp}.json")

        report = {
            "project_id": self.project_id,
            "start_time": self.start_time.isoformat(),
            "end_time": datetime.now().isoformat(),
            "total_events": len(self.events),
            "total_tool_calls": len(self.tool_calls),
            "total_errors": len(self.errors),
            "events": self.events,
            "tool_calls": self.tool_calls,
            "errors": self.errors,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)

        logger.info(f"审计日志已保存: {filepath}")
        return filepath

    def summary(self) -> dict:
        """返回当前审计摘要。"""
        return {
            "project_id": self.project_id,
            "total_events": len(self.events),
            "total_tool_calls": len(self.tool_calls),
            "total_errors": len(self.errors),
            "phases": list(set(e.get("details", {}).get("from", "") for e in self.events if e["type"] == "phase_change")),
            "last_event": self.events[-1]["message"] if self.events else "N/A",
        }

    @staticmethod
    def _sanitize_args(args: dict) -> dict:
        """清理工具参数中的敏感信息。"""
        sanitized = {}
        for k, v in args.items():
            if k in ("token", "password", "secret", "api_key"):
                sanitized[k] = "***REDACTED***"
            elif isinstance(v, str) and len(v) > 1000:
                sanitized[k] = v[:1000] + "..."
            else:
                sanitized[k] = v
        return sanitized
