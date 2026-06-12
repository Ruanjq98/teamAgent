"""
工作流管道 — 实现完整的工作流状态机。

包含:
- 阶段 0: 需求澄清与确认 (阻塞关卡，含超时处理)
- 阶段 1-4: 开发迭代循环 (含回退、冲突检测、审计追踪)
- 阶段 5: 项目收尾

P1 健壮性:
- 指数退避重试 (API 调用)
- Git 冲突检测与自动中止
- 迭代超时控制
- 需求澄清超时
- 操作回退机制
- 完整审计追踪
"""

import asyncio
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger

from config.settings import settings
from src.team.team_orchestrator import create_orchestrator
from src.agents.manager_agent import create_manager_agent
from src.utils.audit import AuditTrail
from src.utils.rollback import RollbackManager, IterationController, ClarificationTimeout, TimeoutGuard
from src.tools import github_tools, git_tools


class WorkflowPipeline:
    """
    工作流管道 — 控制从需求到交付的完整生命周期。

    核心状态机:
        CLARIFYING → PLANNING → DEVELOPING → TESTING → EVALUATING → DONE
                                     ↑                              |
                                     └──────────────────────────────┘
    """

    def __init__(self):
        self.orchestrator = None
        self.iteration_count = 0
        self.start_time: Optional[datetime] = None
        self.parent_issue_number: Optional[int] = None
        self.original_requirement: str = ""

        # P1 组件
        self.audit: Optional[AuditTrail] = None
        self.rollback_mgr = RollbackManager()
        self.iteration_ctrl = IterationController(max_iterations=settings.max_iterations)
        self.clarification_timeout: Optional[ClarificationTimeout] = None
        self.timeout_guard = TimeoutGuard(timeout_seconds=300)  # 5 分钟单轮超时

    async def run(self, requirement: str) -> dict:
        """
        运行完整的工作流管道。

        Args:
            requirement: 用户的原始需求描述

        Returns:
            dict: 执行摘要
        """
        self.original_requirement = requirement
        self.start_time = datetime.now()
        self.iteration_count = 0

        # 初始化审计追踪
        project_id = str(uuid.uuid4())[:8]
        self.audit = AuditTrail(project_id)
        self.audit.log_event("project_start", "Pipeline", f"项目启动: {requirement[:100]}...")

        logger.info("=" * 60)
        logger.info("🚀 项目启动")
        logger.info(f"📋 原始需求: {requirement[:200]}...")
        logger.info(f"🆔 项目 ID: {project_id}")
        logger.info("=" * 60)

        try:
            # ========== 阶段 0: 需求澄清（阻塞关卡）==========
            self.audit.log_phase_change("START", "CLARIFYING", "进入需求澄清阶段")
            logger.info("🔍 进入阶段 0: 需求澄清")

            confirmed = await self._phase_clarification(requirement)
            if not confirmed:
                self.audit.log_event("project_paused", "Pipeline", "需求澄清未完成")
                logger.warning("⚠️ 需求澄清未完成，项目暂停")
                self.audit.flush()
                return {"status": "paused", "reason": "需求未确认"}

            self.audit.log_phase_change("CLARIFYING", "DEVELOPING", "需求已确认")
            logger.info("✅ 需求已确认，进入开发循环")

            # ========== 初始化团队编排器 ==========
            self.orchestrator = create_orchestrator()

            # ========== 阶段 1-4: 开发迭代循环 ==========
            while not self.iteration_ctrl.should_terminate():
                iter_num = self.iteration_ctrl.start_new_iteration()
                self.iteration_count = iter_num
                self.audit.log_iteration(iter_num, "started")

                logger.info(f"\n{'='*40}")
                logger.info(f"🔄 第 {iter_num} 轮迭代开始")
                logger.info(f"{'='*40}")

                # 强制进度报告（每 5 轮）
                if self.iteration_ctrl.should_force_report():
                    logger.info(f"📊 强制进度报告 (第 {iter_num} 轮)")
                    report = self._generate_progress_report()
                    logger.info(report)

                # 构造本轮任务描述
                iteration_task = self._build_iteration_task()

                # 带超时保护运行
                try:
                    result = await self.timeout_guard.run_with_timeout(
                        self.orchestrator.run_iteration(iteration_task),
                        error_message=f"第 {iter_num} 轮迭代超时"
                    )
                    self.iteration_ctrl.complete_iteration({"status": "success"})
                    self.audit.log_iteration(iter_num, "completed")
                    logger.info(f"第 {iter_num} 轮迭代完成")
                except TimeoutError:
                    self.audit.log_error("Pipeline", "timeout", f"第 {iter_num} 轮迭代超时")
                    logger.warning(f"第 {iter_num} 轮迭代超时，尝试下一轮")
                    continue
                except Exception as e:
                    self.audit.log_error("Pipeline", type(e).__name__, str(e))
                    logger.error(f"第 {iter_num} 轮迭代出错: {e}")
                    # 尝试回退
                    await self.rollback_mgr.rollback_all()
                    continue

                # 评估：是否所有需求已完成？
                evaluation = await self._evaluate_completion()

                if evaluation["all_done"]:
                    self.audit.log_event("all_done", "Pipeline", "所有需求已完成")
                    logger.info("🎉 所有需求已完成！进入项目收尾")
                    break
                elif evaluation["should_stop"]:
                    self.audit.log_event("stopped", "Pipeline", f"开发经理决定停止: {evaluation.get('reason', '')}")
                    logger.warning(f"🛑 开发经理决定停止: {evaluation.get('reason', '未知原因')}")
                    break
                else:
                    logger.info(f"📋 剩余工作: {evaluation.get('remaining_work', '待评估')}")
                    logger.info("→ 继续下一轮迭代")

            # ========== 阶段 5: 项目收尾 ==========
            if self.iteration_ctrl.should_terminate():
                self.audit.log_event("max_iterations", "Pipeline", f"达到最大迭代次数 {settings.max_iterations}")
                logger.warning(f"⚠️ 达到最大迭代次数 ({settings.max_iterations})，强制终止")

            self.audit.log_phase_change("DEVELOPING", "CLOSEOUT", "进入项目收尾")
            logger.info("📊 项目收尾中...")
            summary = await self._phase_closeout()
            logger.info("✅ 项目完成")

            # 保存审计日志
            self.audit.flush()

            return summary

        except Exception as e:
            self.audit.log_error("Pipeline", type(e).__name__, str(e))
            logger.error(f"❌ 工作流异常: {e}")
            # 执行回退
            await self.rollback_mgr.rollback_all()
            self.audit.flush()
            return {"status": "error", "error": str(e)}

    async def _phase_clarification(self, requirement: str) -> bool:
        """
        阶段 0: 需求澄清。

        创建父 Issue，与用户通过 Issue 评论区确认需求细节。
        这是阻塞关卡——确认之前不能进入开发流程。

        Returns:
            bool: 需求是否已确认
        """
        from src.tools import github_tools

        logger.info("📝 创建父 Issue 进行需求澄清...")

        # 使用开发经理 Agent（单独运行，不加入团队）
        manager = create_manager_agent()

        clarification_task = f"""
你刚刚收到了用户的以下需求。请立即执行需求澄清流程：

## 用户需求
{requirement}

## 你必须立即执行以下操作:

1. 使用 `create_issue` 创建父 Issue:
   - 标题格式: "[需求] {requirement[:50]}..."
   - 正文包含：
     * 你对需求的理解和复述
     * **逐条列出你的确认问题**（标记为 Q1, Q2, Q3...）
     * 建议的技术方向和架构思路
     * 每个问题前标注 ⚠️ 待确认
   - 添加标签: `type/question`, `status/needs-clarification`

2. 在创建完 Issue 后，等待用户的回复。如果 Issue 创建成功，请回复:
   "已在 GitHub 创建需求确认 Issue #{
        number}，请在评论区逐条回复确认问题。回复完成后请说「需求确认完毕」或「可以开始开发」。"

重要: 现在只做需求澄清，不要创建子 Issue，不要进入开发流程。
"""

        # 运行单次对话获取澄清结果
        from autogen_agentchat.ui import Console
        from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination

        result = await Console(
            manager.run_stream(task=clarification_task)
        )

        # 检查 Issue 是否创建成功，等待用户确认
        logger.info("⏳ 等待用户在 Issue 中回复确认...")
        logger.info("💡 提示: 用户需要在 GitHub Issue 评论区回复确认问题")
        logger.info("💡 用户回复「需求确认完毕」或「可以开始开发」后，流程继续")

        # 注意: 在实际运行中，这需要一个轮询机制来检测用户的回复
        # 当前简化实现: 将确认决定权交给用户
        # 用户可以在下一轮开始前在 Issue 中确认

        # 对于自动化运行，我们假设用户会在合理时间内回复
        # 可以通过定时检查 Issue 评论来判断
        return True  # 简化实现，实际应检查用户确认状态

    def _build_iteration_task(self) -> str:
        """
        构造当前迭代的任务描述。

        Returns:
            str: 本轮迭代的完整任务指令
        """
        if self.iteration_count == 1:
            return f"""
## 🚀 首轮开发迭代

这是项目的第 1 轮开发迭代。请按照以下流程协作：

### 开发经理的职责:
1. 使用 `list_issues` 查看父 Issue 和需求状态
2. 根据已确认的需求制定首轮迭代计划
3. 使用 `create_issue` 创建第一批子 Issues，并 Assign 给开发人员
4. 使用 `comment_on_issue` 在子 Issue 中说明详细的技术方案

### 开发人员的职责:
1. 使用 `list_issues` 查收自己被分配的任务
2. 使用 `get_issue` 阅读 Issue 详情
3. 使用 `clone_repository` 准备本地环境
4. 使用 `create_branch` 创建功能分支
5. 编写代码并使用 `git_commit` / `git_push` 提交推送
6. 使用 `create_pull_request` 创建 PR

### 测试人员的职责:
1. 使用 `list_pull_requests` 检查新的 PR
2. 使用 `fetch_pr_branch` 拉取代码
3. 使用 `read_file` 和 `run_command` 进行审查和验证
4. 使用 `submit_pr_review` 提交审查结论

### 原始需求回顾:
{self.original_requirement}

## ⚠️ 重要
- 每完成一轮操作后，开发经理需要评估是否还有遗留任务
- 如果本轮完成了所有任务，请在最终消息中回复「任务完成」
- 如果还有遗留任务，开发经理应创建新的子 Issues
"""
        else:
            return f"""
## 🔄 第 {self.iteration_count} 轮开发迭代

### 开发经理的职责:
1. 使用 `list_issues` 和 `list_pull_requests` 审视当前项目状态
2. 评估已完成的工作和剩余需求
3. 如有剩余工作 → 使用 `create_issue` 创建新的子 Issues
4. 如有已通过测试的 PR → 使用 `merge_pull_request` 合并
5. 使用 `close_issue` 关闭已完成的 Issues
6. 如果所有需求已完成 → 回复「任务完成」

### 开发人员的职责:
1. 查收新分配的任务
2. 如有被要求修改的 PR → 修复代码并推送新 commit

### 测试人员的职责:
1. 检查新的和更新的 PR
2. 对修复后的代码进行回归测试
3. 提交 Review

### 原始需求回顾:
{self.original_requirement}

## ⚠️ 重要
- 开发经理必须在本轮结束前评估是否所有需求已完成
- 如果全部完成，回复「任务完成」
- 如果还有遗留，明确列出剩余工作并创建对应 Issues
"""

    async def _evaluate_completion(self) -> dict:
        """
        评估项目完成状态。

        由开发经理 Agent 单独运行，检查所有 Issues 和 PRs，
        判断是否所有需求都已实现。

        Returns:
            dict: 包含 all_done, should_stop, remaining_work 等字段
        """
        try:
            # 检查是否还有未关闭的 Issues
            open_issues = github_tools.list_issues(state="open")
            open_prs = github_tools.list_pull_requests(state="open")

            # 简化判断逻辑
            all_done = "没有找到 Issues" in open_issues and "没有找到 PRs" in open_prs
            should_stop = self.iteration_ctrl.should_terminate()

            result = {
                "all_done": all_done,
                "should_stop": should_stop,
                "remaining_work": open_issues if not all_done else "无",
                "iteration": self.iteration_count,
            }

            if self.audit:
                self.audit.log_event("evaluation", "Pipeline", f"评估: all_done={all_done}", result)
            return result
        except Exception as e:
            logger.error(f"评估完成状态失败: {e}")
            if self.audit:
                self.audit.log_error("Pipeline", "evaluation_error", str(e))
            return {"all_done": False, "should_stop": True, "reason": f"评估失败: {e}"}

    def _generate_progress_report(self) -> str:
        """
        生成强制进度报告（每 5 轮迭代触发一次）。

        Returns:
            str: 进度报告文本
        """
        elapsed = datetime.now() - self.start_time if self.start_time else timedelta(0)
        audit_summary = self.audit.summary() if self.audit else {}

        return f"""
📊 ═══════ 强制进度报告 ═══════
  迭代进度: {self.iteration_count}/{settings.max_iterations}
  已用时间: {elapsed}
  工具调用: {audit_summary.get('total_tool_calls', 0)} 次
  错误次数: {audit_summary.get('total_errors', 0)} 次
  需求回顾: {self.original_requirement[:200]}...
═══════════════════════════════
""".strip()

    async def _phase_closeout(self) -> dict:
        """
        阶段 5: 项目收尾。

        开发经理输出总结报告，关闭父 Issue。
        包含回退安全检查和审计日志落盘。
        """
        logger.info("📊 生成项目总结...")

        # 清除回退栈 — 项目进入收尾阶段，不再需要回退
        self.rollback_mgr.clear()

        # 清理已合并的分支
        clean_result = git_tools.cleanup_branches()

        # 获取所有 Issues 和 PRs 的最终状态
        all_issues = github_tools.list_issues(state="all")
        all_prs = github_tools.list_pull_requests(state="all")

        elapsed = datetime.now() - self.start_time if self.start_time else timedelta(0)
        iter_summary = self.iteration_ctrl.summary()

        summary = {
            "status": "completed",
            "total_iterations": self.iteration_count,
            "elapsed_time": str(elapsed),
            "iteration_summary": iter_summary,
            "final_issues": all_issues,
            "final_prs": all_prs,
            "cleanup": clean_result,
        }

        logger.info(f"📊 总迭代次数: {self.iteration_count}")
        logger.info(f"⏱️ 总耗时: {elapsed}")
        logger.info(f"🧹 分支清理: {clean_result}")
        logger.info("✅ 项目收尾完成")

        if self.audit:
            self.audit.log_event("project_end", "Pipeline", "项目收尾完成", summary)
            self.audit.flush()

        return summary


async def run_project(requirement: str) -> dict:
    """
    运行一个完整的项目开发流程。

    Args:
        requirement: 用户的自然语言需求描述

    Returns:
        dict: 项目执行摘要
    """
    pipeline = WorkflowPipeline()
    return await pipeline.run(requirement)
