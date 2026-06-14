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
import re
import uuid
from datetime import datetime, timedelta
from typing import Optional
from github import GithubException
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
                reason = "需求澄清未完成"
                if self.clarification_timeout and self.clarification_timeout.is_suspended:
                    reason = "需求澄清超时暂停"
                self.audit.log_event("project_paused", "Pipeline", reason)
                logger.warning(f"⚠️ {reason}，项目暂停")
                self.audit.flush()
                return {"status": "paused", "reason": reason}

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
        阶段 0: 需求澄清 — 完整的用户交互轮询循环。

        流程:
        1. 通过经理 Agent 创建父 Issue（带 needs-clarification 标签）
        2. 轮询检测用户在 GitHub Issue 中的回复
        3. 有新回复时，运行经理 Agent 评估是否确认通过
        4. 确认通过（标签变为 confirmed）→ 返回 True
        5. 超时（48h 提醒 / 7d 暂停）→ 返回 False

        Returns:
            bool: 需求是否已确认
        """
        from autogen_agentchat.ui import Console

        logger.info("📝 创建父 Issue 进行需求澄清...")

        # ===== 第 1 步：创建父 Issue =====
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

2. 在创建完 Issue 后，如果 Issue 创建成功，请回复:
   "已在 GitHub 创建需求确认 Issue #NUMBER，请在评论区逐条回复确认问题。回复完成后请说「需求确认完毕」或「可以开始开发」。"

重要: 现在只做需求澄清，不要创建子 Issue，不要进入开发流程。
"""

        await Console(manager.run_stream(task=clarification_task))

        # 查找刚创建的父 Issue（最新带 needs-clarification 标签的 Issue）
        issues_output = github_tools.list_issues(state="open", labels=["status/needs-clarification"])
        match = re.search(r'#(\d+)', issues_output)
        if not match:
            # 回退：查所有 open issues
            issues_output = github_tools.list_issues(state="open")
            match = re.search(r'#(\d+)', issues_output)

        if not match:
            logger.error("❌ 无法找到父 Issue 编号")
            if self.audit:
                self.audit.log_error("Pipeline", "issue_not_found", "无法在仓库中找到创建的父 Issue")
            return False

        parent_issue_number = int(match.group(1))
        self.parent_issue_number = parent_issue_number

        logger.info(f"📝 父 Issue #{parent_issue_number} 已创建")
        logger.info(f"🔗 https://github.com/{settings.github_repo_full}/issues/{parent_issue_number}")

        if self.audit:
            self.audit.log_event(
                "parent_issue_created", "开发经理",
                f"父 Issue #{parent_issue_number} 已创建",
                {"issue_number": parent_issue_number},
            )

        # ===== 第 2 步：初始化追踪状态 =====
        self.clarification_timeout = ClarificationTimeout(
            parent_issue_number,
            reminder_after=timedelta(hours=settings.clarification_reminder_hours),
            suspend_after=timedelta(days=settings.clarification_suspend_days),
        )
        self.clarification_timeout.record_user_reply()  # 从现在开始计时

        bot_username = github_tools._get_bot_username()
        logger.debug(f"Bot 用户名: '{bot_username}'")

        # 建立评论基线
        existing_comments = github_tools._get_issue_comments_raw(parent_issue_number)
        last_user_comment_id = max(
            (c["id"] for c in existing_comments if c["author"] != bot_username),
            default=0,
        )
        last_bot_comment_id = max(
            (c["id"] for c in existing_comments if c["author"] == bot_username),
            default=0,
        )
        logger.debug(f"评论基线: user_id={last_user_comment_id}, bot_id={last_bot_comment_id}")

        poll_interval = settings.clarification_poll_interval
        max_polls = settings.clarification_max_polls

        logger.info("⏳ 等待用户在 GitHub Issue 中回复确认...")
        logger.info(f"💡 请在 https://github.com/{settings.github_repo_full}/issues/{parent_issue_number} 回复")
        logger.info("💡 回复「需求确认完毕」或「可以开始开发」后流程自动继续")
        logger.info(
            f"⏱️ 轮询间隔: {poll_interval}s | "
            f"超时提醒: {settings.clarification_reminder_hours}h | "
            f"超时暂停: {settings.clarification_suspend_days}d"
        )

        # ===== 第 3 步：轮询循环 =====
        poll_count = 0

        while True:
            await asyncio.sleep(poll_interval)
            poll_count += 1
            logger.debug(f"轮询 #{poll_count}: 检查 Issue #{parent_issue_number}...")

            # 最大轮询次数保护
            if 0 < max_polls < poll_count:
                logger.warning(f"⚠️ 达到最大轮询次数 ({max_polls})，暂停项目")
                if self.audit:
                    self.audit.log_event(
                        "clarification_max_polls", "Pipeline",
                        f"达到最大轮询次数 {max_polls}",
                    )
                return False

            try:
                # A. 检查标签是否已变为 confirmed（确定性检测）
                if github_tools.issue_has_label(parent_issue_number, "status/confirmed"):
                    logger.info(f"✅ Issue #{parent_issue_number} 已标记为 confirmed")
                    if self.audit:
                        self.audit.log_event(
                            "clarification_confirmed", "Pipeline",
                            f"Issue #{parent_issue_number} 需求已确认",
                        )
                    return True

                # B. 检测新用户评论
                current_comments = github_tools._get_issue_comments_raw(parent_issue_number)
                new_user_comments = [
                    c for c in current_comments
                    if c["author"] != bot_username and c["id"] > last_user_comment_id
                ]

                if new_user_comments:
                    logger.info(f"🔔 检测到 {len(new_user_comments)} 条新用户回复")
                    self.clarification_timeout.record_user_reply()
                    last_user_comment_id = max(c["id"] for c in new_user_comments)

                    if self.audit:
                        self.audit.log_event(
                            "clarification_user_reply", "用户",
                            f"Issue #{parent_issue_number} 收到 "
                            f"{len(new_user_comments)} 条新回复",
                        )

                    # 运行经理 Agent 评估用户回复
                    confirmed = await self._run_clarification_evaluation(
                        parent_issue_number, requirement
                    )

                    if confirmed:
                        return True

                    # 更新 Bot 评论基线（经理可能发布了追问）
                    updated_comments = github_tools._get_issue_comments_raw(parent_issue_number)
                    new_bot_ids = [
                        c["id"] for c in updated_comments
                        if c["author"] == bot_username and c["id"] > last_bot_comment_id
                    ]
                    if new_bot_ids:
                        last_bot_comment_id = max(new_bot_ids)

                    logger.info("📝 开发经理已提出追问，继续等待用户回复...")
                    continue

                # C. 超时处理
                timeout_status = self.clarification_timeout.check_timeout()

                if timeout_status["should_suspend"]:
                    logger.warning(
                        f"⏰ 需求澄清超时 ({settings.clarification_suspend_days}天未回复)，"
                        f"项目暂停"
                    )
                    github_tools.comment_on_issue(
                        parent_issue_number,
                        "⏰ **项目已暂停**\n\n"
                        f"由于超过 {settings.clarification_suspend_days} 天未收到回复，"
                        "需求澄清流程已自动终止。如需继续，请重新启动项目。",
                    )
                    if self.audit:
                        self.audit.log_event(
                            "clarification_suspended", "Pipeline",
                            f"超时 {settings.clarification_suspend_days} 天未回复",
                        )
                    return False

                if timeout_status["should_remind"]:
                    logger.warning(
                        f"⏰ 已等待超过 {settings.clarification_reminder_hours}h，"
                        f"发送提醒评论"
                    )
                    github_tools.comment_on_issue(
                        parent_issue_number,
                        "⏰ **提醒**\n\n"
                        f"已等待超过 {settings.clarification_reminder_hours} 小时，"
                        "请及时回复确认问题，或回复「需求确认完毕」以继续开发流程。\n"
                        f"超时未回复（{settings.clarification_suspend_days} 天）将自动暂停项目。",
                    )
                    if self.audit:
                        self.audit.log_event(
                            "clarification_reminded", "Pipeline",
                            f"提醒用户回复 Issue #{parent_issue_number}",
                        )

            except GithubException as e:
                logger.error(f"GitHub API 错误 (轮询 #{poll_count}): {e}")
                if hasattr(e, "status") and e.status == 404:
                    logger.error(f"Issue #{parent_issue_number} 不存在")
                    return False
                # API 错误时退避等待
                await asyncio.sleep(poll_interval)
                continue

            except Exception as e:
                logger.error(f"轮询异常 (轮询 #{poll_count}): {e}")
                await asyncio.sleep(poll_interval)
                continue

    async def _run_clarification_evaluation(
        self, issue_number: int, requirement: str
    ) -> bool:
        """
        运行经理 Agent 评估需求澄清是否完成。

        创建一个新的经理 Agent 实例，让 LLM 读取 Issue 评论状态，
        判断是否所有确认问题已得到明确答复，并据此确认或追问。

        Args:
            issue_number: 父 Issue 编号
            requirement: 原始需求描述

        Returns:
            bool: 经理是否已将 Issue 标记为 confirmed
        """
        from autogen_agentchat.ui import Console

        logger.info(f"🔍 运行需求澄清评估 (Issue #{issue_number})...")

        evaluation_prompt = f"""
## 🔍 需求澄清评估 — Issue #{issue_number}

你之前已经在 GitHub 上创建了父 Issue #{issue_number} 并提出了确认问题。
用户现在已经在评论区回复了。

### 你的任务

1. 使用 `get_issue` 或 `get_issue_comments` 读取 Issue #{issue_number} 的内容和最新评论
2. 仔细分析用户的回复，逐条对照你之前提出的确认问题
3. 判断所有确认问题是否已得到明确、无歧义的答复

4. 根据判断结果执行:

   **情况 A — 所有问题已明确 + 用户表达了确认:**
   （用户回复了「需求确认完毕」「可以开始开发」「没问题」「确认」等明确确认词）
   → 调用 `add_labels_to_issue` 为 Issue #{issue_number} 添加 `status/confirmed` 标签
   → 调用 `remove_labels_from_issue` 从 Issue #{issue_number} 移除 `status/needs-clarification` 和 `type/question` 标签
   → 调用 `comment_on_issue` 在 Issue #{issue_number} 发表评论：
     「✅ 需求已确认，可以开始开发。」

   **情况 B — 仍有未明确的问题:**
   → 调用 `comment_on_issue` 在 Issue #{issue_number} 发表追问评论
   → 只追问尚未明确的问题，逐条列出（Q1, Q2, ...）
   → 保持现有标签不变

### 原始需求回顾
{requirement}

### ⚠️ 重要规则
- 这是一个**需求澄清评估**任务，不是重新开始需求澄清
- **绝对不要**创建任何子 Issue
- **绝对不要**进入开发流程或拆解任务
- 只关注用户的回复是否明确了所有确认问题
- 如果用户部分回答了问题但还有遗漏，只追问遗漏的部分
"""

        manager = create_manager_agent()
        await Console(manager.run_stream(task=evaluation_prompt))

        # 检查经理是否已添加 confirmed 标签
        confirmed = github_tools.issue_has_label(issue_number, "status/confirmed")

        if confirmed:
            logger.info(f"✅ 开发经理已确认 Issue #{issue_number} 的需求")
            if self.audit:
                self.audit.log_event(
                    "clarification_evaluation_done", "开发经理",
                    f"Issue #{issue_number} 需求已确认，进入开发阶段",
                )
        else:
            logger.info(f"📝 开发经理为 Issue #{issue_number} 提出了追问")
            if self.audit:
                self.audit.log_event(
                    "clarification_evaluation_followup", "开发经理",
                    f"Issue #{issue_number} 提出追问，继续等待用户回复",
                )

        return confirmed

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
1. 使用 `get_issue` 查看父 Issue #{self.parent_issue_number} 中的已确认需求
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

        # 关闭父 Issue 并发布总结评论
        if self.parent_issue_number:
            try:
                github_tools.comment_on_issue(
                    self.parent_issue_number,
                    f"## 📊 项目总结\n\n"
                    f"- 总迭代次数: {self.iteration_count}\n"
                    f"- 总耗时: {datetime.now() - self.start_time if self.start_time else 'N/A'}\n"
                    f"- 原始需求: {self.original_requirement[:200]}...\n"
                    f"\n*本报告由 teamAgent 自动生成*",
                )
                github_tools.close_issue(
                    self.parent_issue_number,
                    comment="✅ 项目需求已全部完成，关闭父 Issue。",
                )
                logger.info(f"📝 父 Issue #{self.parent_issue_number} 已关闭")
            except Exception as e:
                logger.warning(f"关闭父 Issue #{self.parent_issue_number} 失败: {e}")

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
