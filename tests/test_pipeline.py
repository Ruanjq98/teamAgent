"""
管道集成测试 — 测试工作流管道的阶段转换、循环逻辑、异常处理。
"""

import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


class TestPipelineLifecycle:
    """管道生命周期测试。"""

    def test_pipeline_initialization(self):
        """测试管道初始化。"""
        from workflows.pipeline import WorkflowPipeline

        p = WorkflowPipeline()
        assert p.iteration_count == 0
        assert p.original_requirement == ""
        assert p.orchestrator is None
        assert p.rollback_mgr is not None
        assert p.iteration_ctrl is not None
        assert p.timeout_guard is not None

    @patch("workflows.pipeline.create_orchestrator")
    @patch("workflows.pipeline.create_manager_agent")
    @patch("src.tools.github_tools.list_issues")
    @patch("src.tools.github_tools.list_pull_requests")
    def test_pipeline_phase_transitions(
        self, mock_list_prs, mock_list_issues,
        mock_create_mgr, mock_create_orch
    ):
        """测试管道阶段转换。"""
        from workflows.pipeline import WorkflowPipeline

        pipeline = WorkflowPipeline()
        pipeline.iteration_count = 0

        mock_list_issues.return_value = "没有找到 Issues"
        mock_list_prs.return_value = "没有找到 PRs"

        mock_orch = MagicMock()
        mock_orch.run_iteration = AsyncMock(return_value="ok")
        mock_create_orch.return_value = mock_orch

        mock_manager = MagicMock()

        async def mock_stream(task):
            """返回一个可被 async for 迭代的异步生成器。"""
            yield type("Msg", (), {"content": "done", "source": "manager"})()
        mock_manager.run_stream = mock_stream
        mock_create_mgr.return_value = mock_manager

        # 简化为跳过复杂的需求澄清阶段，直接测试管道核心
        with patch.object(pipeline, "_phase_clarification", return_value=True):
            result = asyncio.run(pipeline.run("Test requirement"))
            assert result["status"] == "completed"

    def test_evaluate_completion_all_done(self):
        """测试评估：所有任务完成。"""
        from workflows.pipeline import WorkflowPipeline

        pipeline = WorkflowPipeline()

        with patch("src.tools.github_tools.list_issues", return_value="没有找到 Issues"):
            with patch("src.tools.github_tools.list_pull_requests", return_value="没有找到 PRs"):
                result = asyncio.run(pipeline._evaluate_completion())
                assert result["all_done"] == True
                assert result["remaining_work"] == "无"

    def test_evaluate_completion_has_work(self):
        """测试评估：还有剩余任务。"""
        from workflows.pipeline import WorkflowPipeline

        pipeline = WorkflowPipeline()

        with patch("src.tools.github_tools.list_issues", return_value="仍有 open issues"):
            with patch("src.tools.github_tools.list_pull_requests", return_value="仍有 open PRs"):
                result = asyncio.run(pipeline._evaluate_completion())
                assert result["all_done"] == False

    def test_iteration_task_builder_first(self):
        """测试首轮迭代任务构建。"""
        from workflows.pipeline import WorkflowPipeline

        pipeline = WorkflowPipeline()
        pipeline.original_requirement = "Build a calculator"
        pipeline.iteration_count = 1

        task = pipeline._build_iteration_task()
        assert "首轮" in task
        assert "Build a calculator" in task
        assert "开发经理" in task

    def test_iteration_task_builder_later(self):
        """测试后续迭代任务构建。"""
        from workflows.pipeline import WorkflowPipeline

        pipeline = WorkflowPipeline()
        pipeline.original_requirement = "Build a calculator"
        pipeline.iteration_count = 3

        task = pipeline._build_iteration_task()
        assert "第 3 轮" in task
        assert "Build a calculator" in task

    def test_progress_report_generation(self):
        """测试进度报告生成。"""
        from workflows.pipeline import WorkflowPipeline
        from datetime import datetime

        pipeline = WorkflowPipeline()
        pipeline.original_requirement = "Test project"
        pipeline.iteration_count = 5
        pipeline.start_time = datetime.now()

        report = pipeline._generate_progress_report()
        assert "强制进度报告" in report or "进度报告" in report
        assert "5/" in report


class TestIterationController:
    """迭代控制器测试。"""

    def test_basic_iteration(self):
        """测试基本迭代控制。"""
        from src.utils.rollback import IterationController

        ctrl = IterationController(max_iterations=10)
        assert not ctrl.should_terminate()

        for i in range(9):
            ctrl.start_new_iteration()
            ctrl.complete_iteration({"status": "ok"})

        assert ctrl.current_iteration == 9
        assert not ctrl.should_terminate()
        assert ctrl.should_force_report() == False

        ctrl.start_new_iteration()
        assert ctrl.current_iteration == 10
        assert ctrl.should_terminate()

    def test_force_report_at_5(self):
        """测试第 5 轮强制报告。"""
        from src.utils.rollback import IterationController

        ctrl = IterationController(max_iterations=20)
        for _ in range(4):
            ctrl.start_new_iteration()
        assert not ctrl.should_force_report()

        ctrl.start_new_iteration()
        assert ctrl.should_force_report()

    def test_excessive_review_cycle(self):
        """测试过度审查检测。"""
        from src.utils.rollback import IterationController

        ctrl = IterationController()
        assert ctrl.is_excessive_review_cycle(1, 2) == False
        assert ctrl.is_excessive_review_cycle(1, 4) == True


class TestErrorHandling:
    """异常处理测试。"""

    def test_pipeline_handles_error(self):
        """测试管道优雅处理异常。"""
        from workflows.pipeline import WorkflowPipeline

        pipeline = WorkflowPipeline()

        with patch("src.tools.github_tools.list_issues", side_effect=Exception("API down")):
            result = asyncio.run(pipeline._evaluate_completion())
            assert result["all_done"] == False
            assert result["should_stop"] == True

    def test_rollback_execution(self):
        """测试回退执行。"""
        from src.utils.rollback import RollbackManager

        mgr = RollbackManager()
        steps_executed = []

        mgr.register("step3", lambda: steps_executed.append("step3"))
        mgr.register("step2", lambda: steps_executed.append("step2"))
        mgr.register("step1", lambda: steps_executed.append("step1"))

        rolled_back = asyncio.run(mgr.rollback_all())
        assert steps_executed == ["step1", "step2", "step3"]
        assert len(rolled_back) == 3

    def test_rollback_handles_failure(self):
        """测试回退中某个步骤失败不影响后续。"""
        from src.utils.rollback import RollbackManager

        mgr = RollbackManager()
        executed = []

        def fail_step():
            executed.append("failed")
            raise RuntimeError("boom")

        mgr.register("bad", fail_step)
        mgr.register("good", lambda: executed.append("good"))

        rolled_back = asyncio.run(mgr.rollback_all())
        assert "good" in executed
        assert "failed" in executed
        assert executed == ["good", "failed"]
        assert len(rolled_back) == 1


# ========== 需求澄清阶段测试 ==========


class TestPhaseClarification:
    """需求澄清循环测试。"""

    def test_pipeline_pauses_on_clarification_failure(self):
        """当 _phase_clarification 返回 False 时管道暂停。"""
        from workflows.pipeline import WorkflowPipeline

        pipeline = WorkflowPipeline()

        with patch.object(pipeline, "_phase_clarification", return_value=False):
            result = asyncio.run(pipeline.run("Test requirement"))
            assert result["status"] == "paused"
            assert "需求" in result["reason"]

    @patch("workflows.pipeline.github_tools.issue_has_label")
    @patch("workflows.pipeline.github_tools._get_issue_comments_raw")
    @patch("workflows.pipeline.create_manager_agent")
    def test_clarification_confirmed_on_first_poll(
        self, mock_create_mgr, mock_get_comments, mock_has_label,
    ):
        """测试第一次轮询检测到 confirmed 标签直接返回 True。"""
        from workflows.pipeline import WorkflowPipeline

        pipeline = WorkflowPipeline()
        pipeline.audit = MagicMock()

        mock_has_label.return_value = True
        mock_get_comments.return_value = []

        # Mock stream with create_issue tool result containing issue number
        class FakeCreateIssueResult:
            content = "Issue 创建成功: https://github.com/o/r/issues/1 (编号 #1)"

        class FakeMsg:
            content = [FakeCreateIssueResult()]

            def to_text(self):
                return "Issue 创建成功: https://github.com/o/r/issues/1 (编号 #1)"

        async def mock_stream(task):
            yield FakeMsg()

        mock_manager = MagicMock()
        mock_manager.run_stream = mock_stream
        mock_create_mgr.return_value = mock_manager

        with patch("workflows.pipeline.settings.clarification_poll_interval", 0.01):
            result = asyncio.run(
                pipeline._phase_clarification("Test requirement")
            )
            assert result is True

    @patch("workflows.pipeline.github_tools.issue_has_label")
    @patch("workflows.pipeline.github_tools._get_issue_comments_raw")
    @patch("workflows.pipeline.create_manager_agent")
    def test_clarification_extracts_issue_number(
        self, mock_create_mgr, mock_get_comments, mock_has_label,
    ):
        """测试 Issue 编号从工具调用结果中提取。"""
        from workflows.pipeline import WorkflowPipeline

        pipeline = WorkflowPipeline()
        pipeline.audit = MagicMock()

        mock_has_label.return_value = True
        mock_get_comments.return_value = []

        class FakeCreateIssueResult:
            content = "Issue 创建成功: https://github.com/o/r/issues/42 (编号 #42)"

        class FakeMsg:
            content = [FakeCreateIssueResult()]

            def to_text(self):
                return "Issue 创建成功: https://github.com/o/r/issues/42 (编号 #42)"

        async def mock_stream(task):
            yield FakeMsg()

        mock_manager = MagicMock()
        mock_manager.run_stream = mock_stream
        mock_create_mgr.return_value = mock_manager

        with patch("workflows.pipeline.settings.clarification_poll_interval", 0.01):
            result = asyncio.run(
                pipeline._phase_clarification("Test")
            )
            assert result is True
            assert pipeline.parent_issue_number == 42

    @patch("workflows.pipeline.github_tools.issue_has_label")
    @patch("workflows.pipeline.github_tools._get_issue_comments_raw")
    @patch("workflows.pipeline.github_tools.comment_on_issue")
    @patch("workflows.pipeline.create_manager_agent")
    def test_clarification_suspends_after_timeout(
        self, mock_create_mgr, mock_comment, mock_get_comments, mock_has_label,
    ):
        """测试超时后项目暂停。"""
        from workflows.pipeline import WorkflowPipeline

        pipeline = WorkflowPipeline()
        pipeline.audit = MagicMock()

        mock_has_label.return_value = False
        mock_get_comments.return_value = []

        class FakeCreateIssueResult:
            content = "Issue 创建成功: https://github.com/o/r/issues/1 (编号 #1)"

        class FakeMsg:
            content = [FakeCreateIssueResult()]

            def to_text(self):
                return "Issue created"

        async def mock_stream(task):
            yield FakeMsg()

        mock_manager = MagicMock()
        mock_manager.run_stream = mock_stream
        mock_create_mgr.return_value = mock_manager

        with patch("workflows.pipeline.settings.clarification_poll_interval", 0.01):
            with patch("workflows.pipeline.settings.clarification_max_polls", 2):
                result = asyncio.run(
                    pipeline._phase_clarification("Test")
                )
                assert result is False

    def test_clarification_timeout_reset_on_reply(self):
        """测试新回复重置超时计时器。"""
        from src.utils.rollback import ClarificationTimeout
        from datetime import timedelta

        ct = ClarificationTimeout(
            issue_number=1,
            reminder_after=timedelta(seconds=0.01),
            suspend_after=timedelta(days=7),
        )
        ct.record_user_reply()

        import time
        time.sleep(0.02)

        # Should trigger reminder
        result = ct.check_timeout()
        assert result["should_remind"] is True

        # New reply resets
        ct.record_user_reply()
        result = ct.check_timeout()
        assert result["should_remind"] is False
        assert result["should_suspend"] is False
