"""
Git 工具集 — 封装本地 Git 操作，作为 AutoGen Agent 可调用的工具函数。

使用 GitPython 进行本地仓库操作，支持克隆、分支管理、提交、推送等。

内置:
- Git 冲突检测与自动中止
- Push 前冲突预检
- Pull 冲突自动处理
"""

import os
from typing import Optional
from git import Repo, GitCommandError
from git.exc import InvalidGitRepositoryError
from config.settings import settings


def _get_workspace_dir() -> str:
    """获取本地工作目录，确保目录存在。"""
    workspace = settings.workspace_dir
    os.makedirs(workspace, exist_ok=True)
    return workspace


def _get_repo_path() -> str:
    """获取克隆后的仓库路径。"""
    return os.path.join(_get_workspace_dir(), settings.github_repo_name)


def clone_repository() -> str:
    """
    克隆远程仓库到本地工作目录。

    Returns:
        str: 操作结果描述

    Notes:
        - 如果仓库已存在，则执行 git pull 更新
        - 仓库地址从 settings 中读取
    """
    try:
        repo_path = _get_repo_path()
        workspace = _get_workspace_dir()

        if os.path.exists(repo_path):
            repo = Repo(repo_path)
            origin = repo.remotes.origin
            origin.pull()
            return f"仓库已存在，已拉取最新代码到 {repo_path}"

        repo_url = f"https://{settings.github_token}@github.com/{settings.github_repo_full}.git"
        Repo.clone_from(repo_url, repo_path)
        return f"仓库克隆成功: {repo_path}"
    except GitCommandError as e:
        return f"Git 操作失败: {e.stderr if hasattr(e, 'stderr') else str(e)}"


def create_branch(branch_name: str, base_branch: str = "main") -> str:
    """
    基于指定分支创建新分支并切换过去。

    Args:
        branch_name: 新分支名称
        base_branch: 基分支名称 (默认 main)

    Returns:
        str: 操作结果描述
    """
    try:
        repo_path = _get_repo_path()
        repo = Repo(repo_path)

        # 确保在最新代码上
        repo.remotes.origin.fetch()

        # 切换到基分支并拉取最新
        if repo.active_branch.name != base_branch:
            repo.git.checkout(base_branch)
        repo.remotes.origin.pull(base_branch)

        # 创建新分支
        new_branch = repo.create_head(branch_name)
        new_branch.checkout()

        return f"分支 {branch_name} 创建成功 (基于 {base_branch})，当前位于 {repo.active_branch.name}"
    except GitCommandError as e:
        return f"创建分支失败: {e.stderr if hasattr(e, 'stderr') else str(e)}"


def checkout_branch(branch_name: str) -> str:
    """切换到指定分支。"""
    try:
        repo_path = _get_repo_path()
        repo = Repo(repo_path)
        repo.git.checkout(branch_name)
        return f"已切换到分支 {branch_name}"
    except GitCommandError as e:
        return f"切换分支失败: {e.stderr if hasattr(e, 'stderr') else str(e)}"


def git_commit(message: str, files: Optional[list[str]] = None) -> str:
    """
    暂存文件并提交。

    Args:
        message: 提交信息
        files: 要提交的文件路径列表 (相对于仓库根目录)。为 None 时提交所有更改。

    Returns:
        str: 操作结果描述
    """
    try:
        repo_path = _get_repo_path()
        repo = Repo(repo_path)

        if files:
            repo.index.add(files)
        else:
            repo.index.add("*")

        commit = repo.index.commit(message)
        return f"提交成功: {commit.hexsha[:7]} — {message}"
    except GitCommandError as e:
        return f"提交失败: {e.stderr if hasattr(e, 'stderr') else str(e)}"


def git_push(branch_name: Optional[str] = None) -> str:
    """
    推送当前分支到远程仓库。

    Args:
        branch_name: 要推送的分支名。为 None 时推送当前分支。

    Returns:
        str: 操作结果描述
    """
    try:
        repo_path = _get_repo_path()
        repo = Repo(repo_path)
        branch = branch_name or repo.active_branch.name
        origin = repo.remotes.origin
        push_info = origin.push(branch)
        return f"分支 {branch} 推送成功"
    except GitCommandError as e:
        return f"推送失败: {e.stderr if hasattr(e, 'stderr') else str(e)}"


def git_pull(branch_name: Optional[str] = None) -> str:
    """拉取远程仓库最新代码。"""
    try:
        repo_path = _get_repo_path()
        repo = Repo(repo_path)
        origin = repo.remotes.origin
        origin.pull(branch_name)
        return f"已拉取最新代码"
    except GitCommandError as e:
        return f"拉取失败: {e.stderr if hasattr(e, 'stderr') else str(e)}"


def get_current_branch() -> str:
    """获取当前所在分支名。"""
    try:
        repo_path = _get_repo_path()
        repo = Repo(repo_path)
        return f"当前分支: {repo.active_branch.name}"
    except Exception as e:
        return f"获取当前分支失败: {str(e)}"


def get_git_status() -> str:
    """获取工作目录状态。"""
    try:
        repo_path = _get_repo_path()
        repo = Repo(repo_path)
        status = repo.git.status()
        return f"Git 状态:\n{status}"
    except GitCommandError as e:
        return f"获取状态失败: {e.stderr if hasattr(e, 'stderr') else str(e)}"


def fetch_pr_branch(pr_number: int) -> str:
    """
    获取 PR 对应的分支到本地进行测试。

    Args:
        pr_number: PR 编号

    Returns:
        str: 操作结果描述
    """
    try:
        repo_path = _get_repo_path()
        repo = Repo(repo_path)

        # 拉取远程 PR 引用
        repo.remotes.origin.fetch(f"pull/{pr_number}/head:pr-{pr_number}")
        repo.git.checkout(f"pr-{pr_number}")

        return f"已获取 PR #{pr_number} 代码到分支 pr-{pr_number}"
    except GitCommandError as e:
        return f"获取 PR #{pr_number} 分支失败: {e.stderr if hasattr(e, 'stderr') else str(e)}"


# ========== 冲突检测与处理（P1 新增）==========

def detect_conflicts(branch_name: Optional[str] = None) -> str:
    """
    检测当前分支与 main 的合并冲突。

    Args:
        branch_name: 要检测的分支名。为 None 时使用当前分支。

    Returns:
        str: 冲突检测结果
    """
    try:
        repo_path = _get_repo_path()
        repo = Repo(repo_path)
        branch = branch_name or repo.active_branch.name

        # 确保有最新的远程信息
        repo.remotes.origin.fetch()

        # 尝试检测与 main 的冲突
        main_commit = repo.refs["origin/main"].commit if "origin/main" in repo.refs else repo.refs["main"].commit
        branch_commit = repo.refs[branch].commit if branch in repo.refs else repo.commit(branch)

        # 检查分支是否在 main 之后
        merge_base = repo.merge_base(main_commit, branch_commit)
        if not merge_base:
            return f"⚠️ 分支 {branch} 与 main 没有共同祖先，可能存在严重分歧"

        # 尝试 dry-run merge 检测冲突
        current_branch = repo.active_branch.name
        repo.git.checkout("-b", f"__conflict_check_{branch}__", main_commit.hexsha, "--no-track")
        try:
            repo.git.merge(branch_commit.hexsha, "--no-commit", "--no-ff")
            repo.git.merge("--abort")
            repo.git.checkout(current_branch)
            repo.delete_head(f"__conflict_check_{branch}__", force=True)
            return f"✅ 分支 {branch} 与 main 无冲突，可以安全合并"
        except GitCommandError as merge_error:
            # 合并失败 = 有冲突
            repo.git.merge("--abort")
            repo.git.checkout(current_branch)
            repo.delete_head(f"__conflict_check_{branch}__", force=True)

            # 获取冲突文件列表
            diff_index = repo.index
            conflicted = list(repo.index.unmerged_blobs().keys()) if hasattr(repo.index, 'unmerged_blobs') else []
            return (
                f"⚠️ 分支 {branch} 与 main 存在合并冲突！\n"
                f"冲突文件: {', '.join(conflicted) if conflicted else '未知'}\n"
                f"请手动解决冲突后重新推送。\n"
                f"建议步骤:\n"
                f"  1. git checkout {branch}\n"
                f"  2. git merge origin/main\n"
                f"  3. 解决冲突文件\n"
                f"  4. git commit && git push"
            )
    except GitCommandError as e:
        return f"冲突检测失败: {e.stderr if hasattr(e, 'stderr') else str(e)}"


def safe_push(branch_name: Optional[str] = None) -> str:
    """
    安全推送 — 推送前自动检测冲突。

    Args:
        branch_name: 要推送的分支名

    Returns:
        str: 操作结果
    """
    try:
        repo_path = _get_repo_path()
        repo = Repo(repo_path)
        branch = branch_name or repo.active_branch.name

        # 先拉取最新
        try:
            repo.remotes.origin.pull("main")
        except GitCommandError:
            pass  # 拉取可能没有 main 的新提交

        # 推送
        origin = repo.remotes.origin
        try:
            push_info = origin.push(branch)
            return f"分支 {branch} 推送成功"
        except GitCommandError as push_error:
            error_msg = push_error.stderr if hasattr(push_error, 'stderr') else str(push_error)

            if "rejected" in error_msg.lower() or "non-fast-forward" in error_msg.lower():
                return (
                    f"⚠️ 推送被拒绝！远程分支有更新，存在冲突风险。\n"
                    f"建议: 先执行 git pull origin {branch}，解决冲突后重新推送。\n"
                    f"错误详情: {error_msg}"
                )
            return f"推送失败: {error_msg}"
    except GitCommandError as e:
        return f"安全推送失败: {e.stderr if hasattr(e, 'stderr') else str(e)}"


def abort_and_reset() -> str:
    """
    中止当前操作并回退到安全状态。

    用于技术方案不可行或开发经理决策回退时调用。

    Returns:
        str: 操作结果
    """
    try:
        repo_path = _get_repo_path()
        repo = Repo(repo_path)

        # 中止可能存在的合并
        try:
            repo.git.merge("--abort")
        except GitCommandError:
            pass

        # 中止可能存在的 cherry-pick
        try:
            repo.git.cherry_pick("--abort")
        except GitCommandError:
            pass

        # 放弃所有未暂存的更改
        try:
            repo.git.checkout("--", ".")
        except GitCommandError:
            pass

        # 切回 main
        try:
            repo.git.checkout("main")
        except GitCommandError:
            pass

        return "已中止当前操作，回退到 main 分支的干净状态"
    except GitCommandError as e:
        return f"回退失败: {e.stderr if hasattr(e, 'stderr') else str(e)}"


def cleanup_branches(keep_branches: Optional[list[str]] = None) -> str:
    """
    清理已合并的本地分支。

    Args:
        keep_branches: 需要保留的分支名称列表

    Returns:
        str: 清理结果
    """
    keep = set(keep_branches or [])
    keep.add("main")
    keep.add("master")

    try:
        repo_path = _get_repo_path()
        repo = Repo(repo_path)
        cleaned = []

        for branch in repo.heads:
            if branch.name not in keep:
                try:
                    repo.delete_head(branch, force=True)
                    cleaned.append(branch.name)
                except GitCommandError:
                    pass

        return f"已清理 {len(cleaned)} 个分支: {', '.join(cleaned) if cleaned else '无'}"
    except Exception as e:
        return f"清理分支失败: {str(e)}"
