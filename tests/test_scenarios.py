"""
测试用例库 — 3-5 个不同难度的测试场景，用于回归测试。
"""

import asyncio
import pytest
from unittest.mock import MagicMock, patch


# ============================================================
# 场景定义
# ============================================================

SCENARIO_1_SIMPLE = {
    "name": "场景1: 创建单个文件",
    "difficulty": "easy",
    "input": "在仓库根目录创建一个 CONTRIBUTING.md 文件",
    "expected_issues": 1,
    "expected_prs": 1,
    "expected_iterations": "1-2",
    "verification_points": [
        "开发经理创建 1 个 Issue",
        "开发人员创建功能分支",
        "文件被创建",
        "测试人员审查通过",
        "开发经理合并 PR",
    ],
}

SCENARIO_2_MEDIUM = {
    "name": "场景2: 功能模块开发",
    "difficulty": "medium",
    "input": "添加 math_helpers 模块（add/subtract + pytest 测试）",
    "expected_issues": "2-3",
    "expected_prs": 1,
    "expected_iterations": "2-4",
    "verification_points": [
        "任务拆解为代码+测试",
        "多文件被创建",
        "pytest 验证通过",
        "多轮 Review 可能发生",
    ],
}

SCENARIO_3_BUGFIX = {
    "name": "场景3: Bug 修复回归验证",
    "difficulty": "medium",
    "input": "修复空输入导致崩溃的问题",
    "expected_issues": "1-2",
    "expected_prs": 1,
    "expected_iterations": "2-3",
    "verification_points": [
        "Bug Issue 标签为 type/bug",
        "修复代码 + 验证",
        "回归测试无新问题",
    ],
}

SCENARIO_4_COMPLEX = {
    "name": "场景4: 多模块交互系统",
    "difficulty": "hard",
    "input": "添加 JSON 配置管理系统（ConfigManager + 异常处理 + 测试 + README）",
    "expected_issues": "3-5",
    "expected_prs": "2-3",
    "expected_iterations": "4-8",
    "verification_points": [
        "拆解为多个子 Issue",
        "多轮编码和 Review",
        "异常路径被覆盖",
        "所有子 Issue 关闭",
    ],
}

SCENARIO_5_CHANGE = {
    "name": "场景5: 需求变更适应",
    "difficulty": "hard",
    "input": "初始: CLI 计算器 → 中期变更: 支持文件批量计算",
    "expected_issues": "4-6",
    "expected_prs": "2-4",
    "expected_iterations": "5-10",
    "verification_points": [
        "正确识别需求变更",
        "新需求加入迭代",
        "已有代码不破坏",
        "最终全部满足",
    ],
}

ALL_SCENARIOS = [
    SCENARIO_1_SIMPLE,
    SCENARIO_2_MEDIUM,
    SCENARIO_3_BUGFIX,
    SCENARIO_4_COMPLEX,
    SCENARIO_5_CHANGE,
]


# ============================================================
# 场景 1 测试：简单任务
# ============================================================

class TestScenario1Simple:
    def test_issue_creation(self):
        """验证简单任务创建 Issue。"""
        with patch("src.tools.github_tools._get_repo") as mock_repo_fn:
            mock_repo = MagicMock()
            mock_issue = MagicMock()
            mock_issue.html_url = "https://github.com/owner/repo/issues/1"
            mock_issue.number = 1
            mock_repo.create_issue.return_value = mock_issue
            mock_repo_fn.return_value = mock_repo

            from src.tools.github_tools import create_issue

            result = create_issue(
                title="[任务] 创建 CONTRIBUTING.md",
                body="## 需求\n创建贡献指南文件",
                labels=["type/task"],
            )
            assert "Issue 创建成功" in result

    def test_file_creation(self):
        """模拟文件创建。"""
        from src.tools.file_tools import write_file

        with patch("src.tools.file_tools._safe_path") as mock_safe:
            mock_safe.return_value = "/fake/repo/CONTRIBUTING.md"
            with patch("builtins.open", MagicMock()):
                with patch("os.makedirs"):
                    result = write_file("CONTRIBUTING.md", "# Contributing Guide")
                    assert "写入成功" in result


# ============================================================
# 场景 2 测试：中等任务
# ============================================================

class TestScenario2Medium:
    def test_multi_file_structure(self):
        """验证多文件创建。"""
        from src.tools.file_tools import write_file

        with patch("src.tools.file_tools._safe_path", side_effect=lambda p: f"/fake/repo/{p}"):
            with patch("builtins.open", MagicMock()):
                with patch("os.makedirs"):
                    r1 = write_file("utils/math_helpers.py", "def add(a,b): return a+b\n")
                    r2 = write_file("tests/test_math_helpers.py", "def test_add(): pass\n")
                    assert "写入成功" in r1
                    assert "写入成功" in r2

    def test_pr_review_flow(self):
        """验证 PR Review 流程。"""
        with patch("src.tools.github_tools._get_repo") as mock_repo_fn:
            mock_repo = MagicMock()
            mock_pr = MagicMock()
            mock_pr.number = 5
            mock_repo.get_pull.return_value = mock_pr
            mock_repo_fn.return_value = mock_repo

            from src.tools.github_tools import submit_pr_review

            r1 = submit_pr_review(5, "缺少类型注解", event="REQUEST_CHANGES")
            r2 = submit_pr_review(5, "修复完成", event="APPROVE")
            assert "修改" in r1 or "Review" in r1
            assert "通过" in r2 or "Review" in r2


# ============================================================
# 场景 3 测试：Bug 修复
# ============================================================

class TestScenario3BugFix:
    def test_bug_label_usage(self):
        """验证 Bug 标签使用。"""
        with patch("src.tools.github_tools._get_repo") as mock_repo_fn:
            mock_repo = MagicMock()
            mock_issue = MagicMock()
            mock_issue.html_url = "https://github.com/owner/repo/issues/2"
            mock_issue.number = 2
            mock_repo.create_issue.return_value = mock_issue
            mock_repo_fn.return_value = mock_repo

            from src.tools.github_tools import create_issue

            result = create_issue(
                title="[Bug] 空输入导致崩溃",
                body="## 复现\n运行不传参数",
                labels=["type/bug", "priority/high"],
            )
            assert "Issue 创建成功" in result

    def test_regression_test(self):
        """验证回归测试。"""
        from src.tools.file_tools import run_command

        with patch("src.tools.file_tools._get_repo_path", return_value="/fake/repo"):
            with patch("subprocess.run") as mock_run:
                mock_result = MagicMock()
                mock_result.stdout = b"2 passed in 0.5s\n"
                mock_result.stderr = b""
                mock_result.returncode = 0
                mock_run.return_value = mock_result

                result = run_command("pytest tests/ -v")
                assert "passed" in str(result)


# ============================================================
# 场景 4 测试：复杂任务
# ============================================================

class TestScenario4Complex:
    def test_multiple_issues_tracking(self):
        """验证多 Issue 跟踪。"""
        with patch("src.tools.github_tools._get_repo") as mock_repo_fn:
            mock_repo = MagicMock()
            mock_repo_fn.return_value = mock_repo

            # Create mock issues
            issues = []
            for i, title in enumerate(["核心实现", "单元测试", "README"], 1):
                mock_issue = MagicMock()
                mock_issue.number = i
                mock_issue.title = title
                mock_issue.state = "open"
                mock_issue.labels = []
                mock_issue.assignees = []
                mock_issue.user.login = "testuser"
                issues.append(mock_issue)

            mock_repo.get_issues.return_value = issues

            from src.tools.github_tools import list_issues

            result = list_issues(state="open")
            assert "仓库" in result

    def test_rollback_scenario(self):
        """验证回退场景。"""
        from src.utils.rollback import RollbackManager

        mgr = RollbackManager()
        operations = []

        mgr.register("cleanup_branch", lambda: operations.append("branch_deleted"))
        mgr.register("revert_file", lambda: operations.append("file_reverted"))

        asyncio.run(mgr.rollback_all())
        assert "file_reverted" in operations
        assert "branch_deleted" in operations


# ============================================================
# 场景 5 测试：需求变更
# ============================================================

class TestScenario5Change:
    def test_clarification_timeout_tracking(self):
        """验证需求澄清超时追踪。"""
        from src.utils.rollback import ClarificationTimeout

        ct = ClarificationTimeout(issue_number=1)
        ct.record_user_reply()

        result = ct.check_timeout()
        assert not result["should_remind"]
        assert not result["should_suspend"]

    def test_extended_iterations(self):
        """验证延长迭代周期的处理。"""
        from src.utils.rollback import IterationController

        ctrl = IterationController(max_iterations=10)
        for _ in range(5):
            ctrl.start_new_iteration()
            ctrl.complete_iteration({"status": "ok"})

        assert ctrl.current_iteration == 5
        assert ctrl.should_force_report()
        assert not ctrl.should_terminate()


# ============================================================
# 场景结构验证
# ============================================================

@pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=[s["name"] for s in ALL_SCENARIOS])
def test_scenario_has_required_fields(scenario):
    """每个场景必须包含必要字段。"""
    assert "name" in scenario
    assert "difficulty" in scenario
    assert "input" in scenario
    assert "expected_issues" in scenario
    assert "verification_points" in scenario
    assert len(scenario["verification_points"]) >= 2


def test_all_difficulties_covered():
    """确保覆盖各难度级别。"""
    difficulties = {s["difficulty"] for s in ALL_SCENARIOS}
    assert "easy" in difficulties
    assert "medium" in difficulties
    assert "hard" in difficulties
    assert len(ALL_SCENARIOS) == 5
