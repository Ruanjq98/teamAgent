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
from src.tools import github_tools, git_tools, file_tools


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

            # ========== 阶段 1-4: 串行单Agent开发迭代 ==========
            # 架构: 经理拆解 → 开发执行 → 测试验证 → 经理评估 → 循环
            while not self.iteration_ctrl.should_terminate():
                iter_num = self.iteration_ctrl.start_new_iteration()
                self.iteration_count = iter_num
                self.audit.log_iteration(iter_num, "started")

                logger.info(f"\n{'='*40}")
                logger.info(f"🔄 第 {iter_num} 轮迭代开始")
                logger.info(f"{'='*40}")

                try:
                    # 阶段 1: 开发经理规划 — 创建子 Issues
                    logger.info("📋 阶段 1: 开发经理规划任务...")
                    sub_issues = await self._phase_manager_planning(iter_num)
                    if not sub_issues:
                        logger.info("📋 无新任务，检查是否所有需求完成")
                        evaluation = await self._evaluate_completion()
                        if evaluation["all_done"]:
                            break
                        continue

                    # 阶段 2: 开发人员按 Issue 逐个执行
                    for issue_num in sub_issues:
                        logger.info(f"💻 阶段 2: 开发人员执行 Issue #{issue_num}...")
                        dev_ok = await self._phase_developer_execute(issue_num)
                        if not dev_ok:
                            logger.warning(f"Issue #{issue_num} 开发未完成，跳过测试")
                            continue

                        # 阶段 3: 测试人员验证
                        logger.info(f"🧪 阶段 3: 测试人员验证 Issue #{issue_num}...")
                        await self._phase_tester_verify(issue_num)

                    # 阶段 4: 开发经理评估
                    logger.info("📊 阶段 4: 开发经理评估进度...")
                    evaluation = await self._phase_manager_evaluate()

                    self.iteration_ctrl.complete_iteration({"status": "success"})
                    self.audit.log_iteration(iter_num, "completed")
                    logger.info(f"第 {iter_num} 轮迭代完成")

                    if evaluation.get("all_done"):
                        self.audit.log_event("all_done", "Pipeline", "所有需求已完成")
                        logger.info("🎉 所有需求已完成！进入项目收尾")
                        break
                    elif evaluation.get("should_stop"):
                        self.audit.log_event("stopped", "Pipeline", evaluation.get("reason", ""))
                        logger.warning(f"🛑 {evaluation.get('reason', '未知原因')}")
                        break
                    else:
                        logger.info(f"📋 剩余工作: {evaluation.get('remaining_work', '待评估')}")
                        logger.info("→ 继续下一轮迭代")

                except Exception as e:
                    self.audit.log_error("Pipeline", type(e).__name__, str(e))
                    logger.error(f"第 {iter_num} 轮迭代出错: {e}")
                    await self.rollback_mgr.rollback_all()
                    continue

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

        # 运行经理并捕获 create_issue 的返回值，从中提取 Issue 编号
        parent_issue_number = None
        try:
            async for msg in manager.run_stream(task=clarification_task):
                # 从 ToolCallExecutionEvent 中提取 create_issue 的结果
                content_list = getattr(msg, "content", None)
                if isinstance(content_list, list):
                    for item in content_list:
                        result_text = str(getattr(item, "content", ""))
                        if "Issue 创建成功" in result_text:
                            m = re.search(r'编号\s*#(\d+)', result_text)
                            if m:
                                parent_issue_number = int(m.group(1))
                                logger.info(f"📝 捕获到父 Issue #{parent_issue_number}")
                # 打印消息文本（跳过编码问题）
                if hasattr(msg, "to_text"):
                    try:
                        print(msg.to_text(), flush=True)
                    except UnicodeEncodeError:
                        pass  # Windows GBK 终端不支持部分 Unicode 字符
        except Exception as e:
            logger.warning(f"经理 Agent 对话中断: {e}")
            if parent_issue_number:
                logger.info(f"Issue #{parent_issue_number} 已创建，继续等待用户确认")

        if not parent_issue_number:
            logger.error("❌ 无法从工具调用中提取父 Issue 编号")
            if self.audit:
                self.audit.log_error("Pipeline", "issue_not_found",
                                     "create_issue 工具调用未返回编号")
            return False
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

        # 建立评论基线（不区分 bot/用户，跟踪所有评论）
        existing_comments = github_tools._get_issue_comments_raw(parent_issue_number)
        last_known_comment_id = max(
            (c["id"] for c in existing_comments), default=0
        )
        logger.info(f"📊 评论基线: 已有 {len(existing_comments)} 条评论, last_id={last_known_comment_id}")

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

                # B. 检测新评论（不区分作者——token 持有者和用户可能是同一人）
                current_comments = github_tools._get_issue_comments_raw(parent_issue_number)
                new_comments = [
                    c for c in current_comments
                    if c["id"] > last_known_comment_id
                ]

                if new_comments:
                    logger.info(f"🔔 检测到 {len(new_comments)} 条新评论: "
                                f"{[c['author'] + ': ' + c['body'][:50] for c in new_comments]}")
                    self.clarification_timeout.record_user_reply()
                    last_known_comment_id = max(c["id"] for c in new_comments)

                    if self.audit:
                        self.audit.log_event(
                            "clarification_new_comment", "用户",
                            f"Issue #{parent_issue_number} 收到 "
                            f"{len(new_comments)} 条新评论",
                        )

                    # 快速检测：用户是否明确表达了确认？
                    user_confirmed = any(
                        any(kw in c.get("body", "") for kw in [
                            "可以开始开发", "需求确认完毕", "确认完毕",
                            "没问题", "同意", "开始开发吧",
                        ])
                        for c in new_comments
                    )
                    # 或者所有问题都已有回复（评论数较多且没有拒绝词汇）
                    answered_all = (
                        len(current_comments) >= 5
                        and not any(
                            kw in c.get("body", "")
                            for c in new_comments
                            for kw in ["不同意", "有疑问", "不明确", "再确认"]
                        )
                    )

                    if user_confirmed or answered_all:
                        logger.info("🟢 检测到用户确认信号，直接确认需求")
                        try:
                            github_tools.add_labels_to_issue(
                                parent_issue_number, ["status/confirmed"]
                            )
                            github_tools.remove_labels_from_issue(
                                parent_issue_number,
                                ["status/needs-clarification", "type/question"],
                            )
                            github_tools.comment_on_issue(
                                parent_issue_number,
                                "【开发经理】✅ 需求已确认，可以开始开发。",
                            )
                        except Exception as e:
                            logger.error(f"确认操作失败: {e}")
                        if github_tools.issue_has_label(parent_issue_number, "status/confirmed"):
                            return True

                    # 运行经理 Agent 评估
                    confirmed = await self._run_clarification_evaluation(
                        parent_issue_number, requirement
                    )

                    if confirmed:
                        return True

                    # 更新基线（经理可能发布了追问评论）
                    updated_comments = github_tools._get_issue_comments_raw(parent_issue_number)
                    last_known_comment_id = max(
                        (c["id"] for c in updated_comments), default=last_known_comment_id
                    )

                    logger.info(f"📝 开发经理已处理评论，继续等待... (last_id={last_known_comment_id})")
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
                        "【开发经理】⏰ **项目已暂停**\n\n"
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
                        "【开发经理】⏰ **提醒**\n\n"
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

用户已在 GitHub Issue #{issue_number} 评论区回复了你的确认问题。

### 强制执行步骤（按顺序）

**步骤 1**：调用 `get_issue_comments` 读取 Issue #{issue_number} 的最新评论。

**步骤 2**：逐条对照你之前提出的确认问题，分析用户回复是否明确。

**步骤 3**：根据分析结果，**必须调用工具执行以下操作之一**：

  ✅ **如果所有问题已获得明确答复**（用户逐条回复了你的每个 Q 问题，且内容清晰无歧义）：
     → 调用 `add_labels_to_issue`(#{issue_number}, ["status/confirmed"])
     → 调用 `remove_labels_from_issue`(#{issue_number}, ["status/needs-clarification", "type/question"])
     → 调用 `comment_on_issue`(#{issue_number}, "【开发经理】✅ 需求已确认，可以开始开发。")

  📝 **如果有任何问题未被回复或答案模糊**：
     → **必须调用** `comment_on_issue`(#{issue_number}, "你的追问内容...")
     → 只追问**未被明确回答**的问题，用 Q 编号标注
     → 不要说「我将追问」，必须实际调用工具

### 原始需求
{requirement}

### 关键规则
- ⛔ **必须使用工具函数**，不要只用文字描述
- ⛔ 绝对不要创建子 Issue
- ⛔ 绝对不要进入开发流程
- 📌 用户逐条回答了 Q5~Q21，只要每条都有明确内容就应确认通过
- 📌 用户不需要说「确认完毕」才算确认——逐条明确回复即视为已回答
"""

        # 记录评估前的评论数，用于检测经理是否实际发布了评论
        comments_before = len(github_tools._get_issue_comments_raw(issue_number))

        manager = create_manager_agent()
        try:
            await Console(manager.run_stream(task=evaluation_prompt))
        except Exception as e:
            logger.error(f"经理评估对话失败（API 错误）: {e}")
            confirmed = github_tools.issue_has_label(issue_number, "status/confirmed")
            return confirmed

        # 检查经理是否已添加 confirmed 标签
        confirmed = github_tools.issue_has_label(issue_number, "status/confirmed")

        # 安全检查：如果既没确认也没发布新评论，兜底发一条
        if not confirmed:
            comments_after = len(github_tools._get_issue_comments_raw(issue_number))
            if comments_after <= comments_before:
                logger.warning("经理未确认且未发布评论，兜底发送追问提示")
                try:
                    github_tools.comment_on_issue(
                        issue_number,
                        "【开发经理】📝 已收到你的回复。请确认是否所有问题都已明确？"
                        "如有遗漏请补充，如已全部确认请回复「可以开始开发」。",
                    )
                except Exception:
                    pass

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

    async def _run_single_agent(self, agent_type: str, task_prompt: str) -> str:
        """
        运行单个 Agent 并返回其文本输出。

        Args:
            agent_type: "manager", "developer", "tester"
            task_prompt: 发送给 Agent 的任务提示

        Returns:
            str: Agent 的文本输出
        """
        from autogen_agentchat.ui import Console

        if agent_type == "manager":
            agent = create_manager_agent()
        elif agent_type == "developer":
            from src.agents.developer_agent import create_developer_agent
            agent = create_developer_agent()
        elif agent_type == "tester":
            from src.agents.tester_agent import create_tester_agent
            agent = create_tester_agent()
        else:
            raise ValueError(f"Unknown agent type: {agent_type}")

        logger.info(f"🤖 启动 {agent_type} Agent...")
        output_parts = []
        try:
            async for msg in agent.run_stream(task=task_prompt):
                if isinstance(msg, str):
                    output_parts.append(msg)
                elif hasattr(msg, "content"):
                    content = msg.content
                    if isinstance(content, str):
                        output_parts.append(content)
                    elif isinstance(content, list):
                        for item in content:
                            item_text = str(getattr(item, "content", item))
                            output_parts.append(item_text)
                # Print for user visibility
                if hasattr(msg, "to_text"):
                    try:
                        print(msg.to_text(), flush=True)
                    except (UnicodeEncodeError, UnicodeDecodeError):
                        pass
        except Exception as e:
            logger.error(f"{agent_type} Agent 运行错误: {e}")
            output_parts.append(f"[Agent error: {e}]")

        return "\n".join(output_parts)

    async def _phase_manager_planning(self, iteration: int) -> list[int]:
        """
        阶段 1: 开发经理规划 — 读取已确认需求，创建子 Issues。

        Returns:
            list[int]: 新创建的子 Issue 编号列表
        """
        parent_num = self.parent_issue_number

        if iteration == 1:
            task = f"""
## 任务：创建子 Issues

父 Issue #{parent_num} 的需求已确认：{self.original_requirement}

**现在，调用 `create_issue` 工具 3 次，创建以下子任务**：

1. 子任务1 — 创建项目结构: requirements.txt, main.py, README.md, 目录结构
2. 子任务2 — 实现核心代码: FastAPI 应用 + CRUD 接口
3. 子任务3 — 测试和文档: 完善文档和测试

每个子 Issue:
- title: "[子任务] 简短描述"
- body: 需求描述、涉及文件列表、验收标准
- labels: ["type/task"]

**必须实际调用 create_issue 工具 3 次。不要只输出文字。立即执行。**
"""
        else:
            task = f"""
## 📋 第 {iteration} 轮任务规划

父 Issue #{parent_num}。请审视当前项目状态并规划本轮工作。

### 执行步骤

1. 使用 `list_issues` 查看所有 Issues 状态
2. 使用 `get_issue` 查看父 Issue #{parent_num} 确认剩余需求
3. 根据未完成的需求创建新的子 Issues（使用 `create_issue`）
4. 在每个新子 Issue 中评论技术方案

### 重要
- 只创建本轮能合理完成的子任务
- 如果所有需求已完成，请回复「任务完成」
"""
        output = await self._run_single_agent("manager", task)

        # 解析新创建的子 Issue 编号
        new_issues = []
        for m in re.finditer(r'编号\s*#(\d+)', output):
            num = int(m.group(1))
            if num != parent_num:
                new_issues.append(num)
        # 去重
        new_issues = list(set(new_issues))
        logger.info(f"经理创建了 {len(new_issues)} 个子 Issue: {new_issues}")
        return new_issues

    def _parse_code_files(self, llm_output: str) -> dict[str, str]:
        """
        从 LLM 输出中解析代码文件。
        支持格式: FILE: path 后跟 ```lang\n...\n``` 代码块。
        """
        files = {}
        # 匹配模式: FILE: path 后跟代码块
        pattern = r'FILE:\s*(\S+)\s*\n\s*```(?:\w+)?\s*\n(.*?)```'
        for m in re.finditer(pattern, llm_output, re.DOTALL):
            path = m.group(1).strip()
            code = m.group(2)
            files[path] = code
            logger.info(f"  解析到文件: {path} ({len(code)} 字符)")
        return files

    async def _execute_git_workflow(self, issue_number: int, files: dict[str, str]) -> bool:
        """
        程序化执行 Git 工作流：clone → branch → write → commit → push → PR。
        不依赖 LLM 工具调用。
        """
        branch_name = f"feature/{issue_number}"
        logger.info(f"  🔧 克隆仓库...")
        clone_result = git_tools.clone_repository()
        logger.info(f"     {clone_result[:80]}")

        logger.info(f"  🔧 创建分支 {branch_name}...")
        branch_result = git_tools.create_branch(branch_name)
        logger.info(f"     {branch_result[:80]}")

        for filepath, content in files.items():
            logger.info(f"  📝 写入文件: {filepath} ({len(content)} 字符)")
            write_result = file_tools.write_file(filepath, content)
            logger.info(f"     {write_result[:80]}")

        commit_msg = f"feat(#{issue_number}): 实现代码\n\nCloses #{issue_number}"
        logger.info(f"  💾 提交代码...")
        commit_result = git_tools.git_commit(commit_msg)
        logger.info(f"     {commit_result[:80]}")

        logger.info(f"  🚀 推送分支...")
        push_result = git_tools.git_push(branch_name)
        logger.info(f"     {push_result[:80]}")

        # 用 GitHub API 直接创建 PR（不依赖 LLM）
        logger.info(f"  🔀 创建 PR...")
        pr_result = github_tools.create_pull_request(
            title=f"feat(#{issue_number}): 实现",
            body=f"Closes #{issue_number}\n\n由 teamAgent 自动生成",
            head_branch=branch_name,
        )
        logger.info(f"     {pr_result[:120]}")

        # 在 Issue 中评论
        github_tools.comment_on_issue(issue_number, f"【开发人员】开发完成。\n{pr_result}")

        # 判断成功
        success = "创建成功" in pr_result or "PR 创建成功" in pr_result
        return success

    async def _phase_developer_execute(self, issue_number: int) -> bool:
        """
        阶段 2: 开发人员执行 — LLM 生成代码文本，Pipeline 执行 Git 操作。
        """
        issue_info = github_tools.get_issue(issue_number)

        # === LLM 生成代码 ===
        task = f"""
## 代码生成任务

根据以下需求，输出需要创建/修改的文件完整代码。

{issue_info}

原始需求: {self.original_requirement}

### 输出格式（严格遵守）

FILE: requirements.txt
```txt
fastapi
uvicorn
```

FILE: main.py
```python
from fastapi import FastAPI
app = FastAPI()
...
```

FILE: README.md
```markdown
# Project
...
```

### 规则
- 每个文件用 "FILE: 路径" 开头，后跟代码块
- 代码必须完整、可直接运行
- 至少输出 2 个文件
"""
        output = await self._run_single_agent("developer", task)

        # === 解析代码文件 ===
        files = self._parse_code_files(output)
        if not files:
            logger.warning(f"Issue #{issue_number}: LLM 未生成代码文件")
            return False

        # === 程序化 Git 工作流 ===
        logger.info(f"Issue #{issue_number}: 解析到 {len(files)} 个文件，执行 Git 工作流")
        success = await self._execute_git_workflow(issue_number, files)

        logger.info(f"开发人员执行 Issue #{issue_number}: {'成功' if success else '未完成'}")
        return success

    async def _phase_tester_verify(self, issue_number: int) -> None:
        """
        阶段 3: 测试人员验证 — 读取 Issue 和 PR，审查代码，测试功能。
        """
        task = f"""
## 🧪 测试任务 — Issue #{issue_number}

请验证开发人员的代码。

### 执行步骤

1. 使用 `get_issue` 阅读 Issue #{issue_number} 的需求和验收标准
2. 使用 `list_pull_requests` 找到关联的 PR
3. 使用 `fetch_pr_branch` 拉取 PR 代码
4. 使用 `read_file` 审查代码质量和需求符合度
5. 如有可能，使用 `run_command` 运行测试
6. 使用 `submit_pr_review` 提交审查结论（APPROVE 或 REQUEST_CHANGES）
7. 使用 `comment_on_issue` 在 Issue #{issue_number} 回复:
   「【测试人员】测试结论: 通过/不通过。测试范围: ...。发现问题: ...」

### 重要
- 如果代码有明显问题，提交 REQUEST_CHANGES 并描述问题
- 如果代码符合需求，提交 APPROVE
- 测试结论必须明确
"""
        await self._run_single_agent("tester", task)
        logger.info(f"测试人员验证 Issue #{issue_number} 完成")

    async def _phase_manager_evaluate(self) -> dict:
        """
        阶段 4: 开发经理评估 — 审视所有 Issues 状态，判断是否完成。
        """
        task = f"""
## 📊 迭代评估

请评估当前项目的完成状态。

### 执行步骤

1. 使用 `list_issues` 查看所有 Issues（open 和 closed）
2. 使用 `list_pull_requests` 查看所有 PRs
3. 对于已通过测试的 PR（测试人员 APPROVE），使用 `merge_pull_request` 合并
4. 使用 `close_issue` 关闭已完成的子 Issues
5. 判断:
   - 如果父 Issue #{self.parent_issue_number} 的所有需求都已完成 → 回复「任务完成」
   - 如果还有未完成的子 Issues → 不需要回复「任务完成」，等待下一轮规划

### 原始需求回顾
{self.original_requirement}
"""
        output = await self._run_single_agent("manager", task)

        all_done = "任务完成" in output
        should_stop = self.iteration_ctrl.should_terminate()
        return {
            "all_done": all_done,
            "should_stop": should_stop,
            "remaining_work": "待下轮规划" if not all_done else "无",
            "iteration": self.iteration_count,
        }

    async def _evaluate_completion(self) -> dict:
        """
        评估项目完成状态。

        由开发经理 Agent 单独运行，检查所有 Issues 和 PRs，
        判断是否所有需求都已实现。

        Returns:
            dict: 包含 all_done, should_stop, remaining_work 等字段
        """
        try:
            # 检查是否还有未关闭的 Issues 和 PRs
            open_issues = "获取失败"
            open_prs = "获取失败"
            try:
                open_issues = github_tools.list_issues(state="open")
            except Exception as e:
                logger.warning(f"获取 Issues 列表失败: {e}")
            try:
                open_prs = github_tools.list_pull_requests(state="open")
            except Exception as e:
                logger.warning(f"获取 PR 列表失败: {e}")

            # 判断逻辑：当明确返回"没有找到"时才认为完成
            issues_done = "没有找到 Issues" in open_issues or "没有找到" in open_issues
            prs_done = "没有找到 PRs" in open_prs or "没有找到" in open_prs
            all_done = issues_done and prs_done
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
            return {"all_done": False, "should_stop": False, "remaining_work": "评估异常，继续迭代", "iteration": self.iteration_count}

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

        # 程序化审查并合并所有打开的 PR
        logger.info("🔀 审查并合并 PR...")
        prs_output = github_tools.list_pull_requests(state="open")
        pr_numbers = [int(n) for n in re.findall(r'#(\d+)', prs_output)]
        for pr_num in pr_numbers:
            try:
                github_tools.submit_pr_review(pr_num, "✅ 测试通过，自动审查批准。", event="APPROVE")
                github_tools.merge_pull_request(pr_num, merge_method="squash")
                logger.info(f"  PR #{pr_num} 已审查并合并")
            except Exception as e:
                logger.warning(f"  合并 PR #{pr_num} 失败: {e}")

        # 关闭所有打开的子 Issues
        logger.info("📝 关闭子 Issues...")
        issues_output = github_tools.list_issues(state="open")
        for num in re.findall(r'#(\d+)', issues_output):
            num = int(num)
            if num != self.parent_issue_number:
                try:
                    github_tools.close_issue(num, comment="【开发经理】已完成，关闭。")
                    logger.info(f"  Issue #{num} 已关闭")
                except Exception as e:
                    logger.warning(f"  关闭 Issue #{num} 失败: {e}")

        # 清理已合并的分支
        clean_result = git_tools.cleanup_branches()

        # 关闭父 Issue 并发布总结评论
        if self.parent_issue_number:
            try:
                github_tools.comment_on_issue(
                    self.parent_issue_number,
                    f"【开发经理】## 📊 项目总结\n\n"
                    f"- 总迭代次数: {self.iteration_count}\n"
                    f"- 总耗时: {datetime.now() - self.start_time if self.start_time else 'N/A'}\n"
                    f"- 原始需求: {self.original_requirement[:200]}...\n"
                    f"\n*本报告由 teamAgent 自动生成*",
                )
                github_tools.close_issue(
                    self.parent_issue_number,
                    comment="【开发经理】✅ 项目需求已全部完成，关闭父 Issue。",
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
