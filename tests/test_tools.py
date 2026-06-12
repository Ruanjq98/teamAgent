"""
工具函数单元测试 — 使用 mock 模拟外部依赖 (GitHub API, Git, 文件系统)。
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch, mock_open


# ========== File Tools Tests ==========


class TestFileTools:
    """文件操作工具测试。"""

    def test_read_file_success(self):
        """测试读取存在的文件。"""
        from src.tools.file_tools import read_file

        with patch("src.tools.file_tools._safe_path") as mock_safe:
            mock_safe.return_value = "/fake/repo/test.py"
            m = mock_open(read_data="print('hello')\nprint('world')\n")
            with patch("builtins.open", m):
                with patch("os.path.exists", return_value=True):
                    with patch("os.path.isdir", return_value=False):
                        result = read_file("test.py")
                        assert "test.py" in result
                        assert "print" in result

    def test_read_file_not_exists(self):
        """测试读取不存在的文件。"""
        from src.tools.file_tools import read_file

        with patch("src.tools.file_tools._safe_path") as mock_safe:
            mock_safe.return_value = "/fake/repo/missing.py"
            with patch("os.path.exists", return_value=False):
                result = read_file("missing.py")
                assert "文件不存在" in result or "not exist" in result.lower()

    def test_write_file_creates_dirs(self):
        """测试写入文件时自动创建父目录。"""
        from src.tools.file_tools import write_file

        with patch("src.tools.file_tools._safe_path") as mock_safe:
            mock_safe.return_value = "/fake/repo/sub/file.py"
            m = mock_open()
            with patch("builtins.open", m):
                with patch("os.makedirs") as mock_mkdirs:
                    result = write_file("sub/file.py", "content")
                    mock_mkdirs.assert_called_once()
                    assert "写入成功" in result

    def test_delete_file_success(self):
        """测试删除文件。"""
        from src.tools.file_tools import delete_file

        with patch("src.tools.file_tools._safe_path") as mock_safe:
            mock_safe.return_value = "/fake/repo/old.py"
            with patch("os.path.exists", return_value=True):
                with patch("os.remove") as mock_remove:
                    result = delete_file("old.py")
                    mock_remove.assert_called_once()
                    assert "已删除" in result

    def test_list_files_structure(self):
        """测试列出文件。"""
        from src.tools.file_tools import list_files

        with patch("src.tools.file_tools._safe_path") as mock_safe:
            mock_safe.return_value = "/fake/repo"
            with patch("os.path.exists", return_value=True):
                with patch("os.path.isdir", return_value=True):
                    with patch("os.listdir", return_value=["main.py", "README.md"]):
                        with patch("os.path.isdir", side_effect=[False, False]):
                            with patch("os.path.getsize", return_value=100):
                                result = list_files(".")
                                assert "目录" in result or "main.py" in result

    def test_safe_path_boundary(self):
        """测试路径越界检测。"""
        from src.tools.file_tools import _safe_path

        with pytest.raises(ValueError):
            _safe_path("../../../etc/passwd")

    def test_run_command(self):
        """测试执行 Shell 命令。"""
        from src.tools.file_tools import run_command

        with patch("src.tools.file_tools._get_repo_path", return_value="/fake/repo"):
            with patch("subprocess.run") as mock_run:
                mock_result = MagicMock()
                mock_result.stdout = b"hello\n"
                mock_result.stderr = b""
                mock_result.returncode = 0
                mock_run.return_value = mock_result

                result = run_command("echo hello")
                assert "hello" in str(result)


# ========== GitHub Tools Tests ==========


class TestGitHubTools:
    """GitHub 工具测试。"""

    def test_create_issue_mock(self):
        """测试创建 Issue（mock GitHub API）。"""
        with patch("src.tools.github_tools._get_repo") as mock_repo_fn:
            mock_repo = MagicMock()
            mock_issue = MagicMock()
            mock_issue.html_url = "https://github.com/owner/repo/issues/1"
            mock_issue.number = 1
            mock_repo.create_issue.return_value = mock_issue
            mock_repo_fn.return_value = mock_repo

            from src.tools.github_tools import create_issue

            result = create_issue("Test Issue", "Test body", labels=["type/task"])
            assert "Issue 创建成功" in result
            mock_repo.create_issue.assert_called_once()

    def test_close_issue_mock(self):
        """测试关闭 Issue。"""
        with patch("src.tools.github_tools._get_repo") as mock_repo_fn:
            mock_repo = MagicMock()
            mock_issue = MagicMock()
            mock_repo.get_issue.return_value = mock_issue
            mock_repo_fn.return_value = mock_repo

            from src.tools.github_tools import close_issue

            result = close_issue(1, comment="done")
            assert "已关闭" in result
            mock_issue.edit.assert_called_once_with(state="closed")

    def test_get_issue_mock(self):
        """测试获取 Issue 详情。"""
        with patch("src.tools.github_tools._get_repo") as mock_repo_fn:
            mock_repo = MagicMock()
            mock_issue = MagicMock()
            mock_issue.number = 1
            mock_issue.title = "Test"
            mock_issue.state = "open"
            mock_issue.labels = []
            mock_issue.assignees = []
            mock_issue.user.login = "testuser"
            mock_issue.html_url = "https://github.com/owner/repo/issues/1"
            mock_issue.body = "Issue body"
            mock_issue.comments = 0
            mock_issue.get_comments.return_value = []
            mock_repo.get_issue.return_value = mock_issue
            mock_repo_fn.return_value = mock_repo

            from src.tools.github_tools import get_issue

            result = get_issue(1)
            assert "Issue #1" in result
            assert "Test" in result

    def test_submit_pr_review_mock(self):
        """测试提交 PR Review。"""
        with patch("src.tools.github_tools._get_repo") as mock_repo_fn:
            mock_repo = MagicMock()
            mock_pr = MagicMock()
            mock_repo.get_pull.return_value = mock_pr
            mock_repo_fn.return_value = mock_repo

            from src.tools.github_tools import submit_pr_review

            result = submit_pr_review(5, "LGTM", event="APPROVE")
            assert "通过" in result or "Review" in result
            mock_pr.create_review.assert_called_once_with(body="LGTM", event="APPROVE")

    def test_merge_pr_mock(self):
        """测试合并 PR。"""
        with patch("src.tools.github_tools._get_repo") as mock_repo_fn:
            mock_repo = MagicMock()
            mock_pr = MagicMock()
            mock_pr.merged = False
            mock_pr.mergeable = True
            mock_repo.get_pull.return_value = mock_pr
            mock_repo_fn.return_value = mock_repo

            from src.tools.github_tools import merge_pull_request

            result = merge_pull_request(5, merge_method="squash")
            assert "已成功合并" in result
            mock_pr.merge.assert_called_once()

    def test_add_labels_to_issue(self):
        """测试为 Issue 添加标签。"""
        with patch("src.tools.github_tools._get_repo") as mock_repo_fn:
            mock_repo = MagicMock()
            mock_issue = MagicMock()
            mock_repo.get_issue.return_value = mock_issue
            mock_repo_fn.return_value = mock_repo

            from src.tools.github_tools import add_labels_to_issue

            result = add_labels_to_issue(3, ["status/confirmed"])
            assert "已为 Issue" in result
            mock_issue.add_to_labels.assert_called_once_with("status/confirmed")


# ========== Git Tools Tests ==========


class TestGitTools:
    """Git 操作工具测试。"""

    def test_clone_repository_already_exists(self):
        """测试仓库已存在时的处理。"""
        with patch("src.tools.git_tools._get_workspace_dir", return_value="/fake/ws"):
            with patch("src.tools.git_tools._get_repo_path", return_value="/fake/ws/repo"):
                with patch("os.path.exists", return_value=True):
                    with patch("src.tools.git_tools.Repo") as MockRepo:
                        mock_repo = MagicMock()
                        mock_origin = MagicMock()
                        mock_repo.remotes.origin = mock_origin
                        MockRepo.return_value = mock_repo

                        from src.tools.git_tools import clone_repository

                        result = clone_repository()
                        assert "仓库已存在" in result
                        mock_origin.pull.assert_called_once()

    def test_create_branch_mock(self):
        """测试创建分支。"""
        with patch("src.tools.git_tools._get_repo_path", return_value="/fake/ws/repo"):
            with patch("src.tools.git_tools.Repo") as MockRepo:
                mock_repo = MagicMock()
                mock_repo.active_branch.name = "main"
                mock_repo.remotes.origin = MagicMock()
                mock_repo.create_head.return_value = MagicMock()
                MockRepo.return_value = mock_repo

                from src.tools.git_tools import create_branch

                result = create_branch("feature/test", base_branch="main")
                assert "分支" in result
                assert "创建成功" in result

    def test_detect_conflicts_no_remote(self):
        """测试冲突检测（无远程引用时优雅降级）。"""
        from src.tools.git_tools import detect_conflicts

        with patch("src.tools.git_tools._get_repo_path", return_value="/fake/ws/repo"):
            with patch("src.tools.git_tools.Repo") as MockRepo:
                mock_repo = MagicMock()
                mock_repo.active_branch.name = "main"
                mock_repo.remotes.origin = MagicMock()
                mock_repo.refs = MagicMock()
                # simulate __contains__ returning False for any ref
                mock_repo.refs.__contains__.return_value = False
                MockRepo.return_value = mock_repo

                result = detect_conflicts("feature/x")
                # Should fail gracefully - actual branches don't exist in mock
                assert isinstance(result, str)
                assert len(result) > 0

    def test_abort_and_reset_mock(self):
        """测试回退到安全状态。"""
        with patch("src.tools.git_tools._get_repo_path", return_value="/fake/ws/repo"):
            with patch("src.tools.git_tools.Repo") as MockRepo:
                mock_repo = MagicMock()
                MockRepo.return_value = mock_repo

                from src.tools.git_tools import abort_and_reset

                result = abort_and_reset()
                assert "回退" in result or "已中止" in result

    def test_cleanup_branches_mock(self):
        """测试分支清理。"""
        with patch("src.tools.git_tools._get_repo_path", return_value="/fake/ws/repo"):
            with patch("src.tools.git_tools.Repo") as MockRepo:
                mock_repo = MagicMock()
                mock_main = MagicMock()
                mock_main.name = "main"
                mock_feature = MagicMock()
                mock_feature.name = "feature/old"
                mock_repo.heads = [mock_main, mock_feature]
                MockRepo.return_value = mock_repo

                from src.tools.git_tools import cleanup_branches

                result = cleanup_branches()
                assert "已清理" in result


# ========== Retry Utility Tests ==========


class TestRetry:
    """重试机制测试。"""

    def test_retry_call_success_first_try(self):
        """测试首次成功不重试。"""
        from src.utils.retry import retry_call

        call_count = [0]

        def flaky_func():
            call_count[0] += 1
            return "ok"

        result = retry_call(flaky_func, max_retries=3)
        assert result == "ok"
        assert call_count[0] == 1

    def test_retry_call_eventual_success(self):
        """测试重试后最终成功。"""
        from src.utils.retry import retry_call

        call_count = [0]

        def flaky_func():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("temp fail")
            return "recovered"

        result = retry_call(flaky_func, max_retries=3)
        assert result == "recovered"
        assert call_count[0] == 3

    def test_retry_call_all_fail(self):
        """测试全部重试失败。"""
        from src.utils.retry import retry_call

        def always_fail():
            raise ConnectionError("permanent fail")

        with pytest.raises(ConnectionError):
            retry_call(always_fail, max_retries=2)


# ========== Audit Tests ==========


class TestAudit:
    """审计追踪测试。"""

    def test_audit_trail_basic(self):
        """测试基本审计功能。"""
        from src.utils.audit import AuditTrail

        trail = AuditTrail("test-proj")
        trail.log_event("test_event", "agent1", "test message")
        trail.log_tool_call("agent1", "tool_x", {"a": 1}, "result ok", 50.0)
        trail.log_error("agent1", "TestError", "something broke")

        summary = trail.summary()
        assert summary["total_events"] == 1
        assert summary["total_tool_calls"] == 1
        assert summary["total_errors"] == 1
        assert summary["project_id"] == "test-proj"

    def test_audit_sanitize_args(self):
        """测试敏感参数过滤。"""
        from src.utils.audit import AuditTrail

        trail = AuditTrail("test")
        sanitized = trail._sanitize_args({
            "token": "secret123",
            "username": "admin",
            "body": "x" * 2000,
        })
        assert sanitized["token"] == "***REDACTED***"
        assert sanitized["username"] == "admin"
        assert len(sanitized["body"]) <= 1003

    def test_audit_flush(self):
        """测试审计日志落盘。"""
        from src.utils.audit import AuditTrail

        trail = AuditTrail("flush-test")
        trail.log_event("test", "x", "msg")
        filepath = trail.flush()

        assert os.path.exists(filepath)
        os.remove(filepath)


# ========== Rollback Tests ==========


class TestRollback:
    """回退机制测试。"""

    def test_rollback_register_and_clear(self):
        """测试注册和清除回退。"""
        from src.utils.rollback import RollbackManager

        mgr = RollbackManager()
        assert mgr.pending_count == 0

        mgr.register("step1", lambda: None)
        assert mgr.pending_count == 1

        mgr.clear()
        assert mgr.pending_count == 0

    def test_iteration_controller(self):
        """测试迭代控制器。"""
        from src.utils.rollback import IterationController

        ctrl = IterationController(max_iterations=10)
        assert ctrl.current_iteration == 0
        assert not ctrl.should_terminate()

        ctrl.start_new_iteration()
        assert ctrl.current_iteration == 1
        assert not ctrl.should_force_report()

        for _ in range(4):
            ctrl.start_new_iteration()
        assert ctrl.current_iteration == 5
        assert ctrl.should_force_report()

    def test_clarification_timeout(self):
        """测试需求澄清超时。"""
        from src.utils.rollback import ClarificationTimeout

        ct = ClarificationTimeout(1)
        result = ct.check_timeout()
        assert not result["should_remind"]

        ct.record_user_reply()
        result = ct.check_timeout()
        assert not result["should_remind"]
        assert not result["should_suspend"]
