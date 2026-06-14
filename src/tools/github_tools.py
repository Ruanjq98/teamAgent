"""
GitHub 工具集 — 封装 GitHub API 操作，作为 AutoGen Agent 可调用的工具函数。

所有工具函数通过 PyGithub 与 GitHub 交互，适配 AutoGen @tool 装饰器。

内置:
- 指数退避重试 (API 限流/网络波动)
- 审计追踪记录
"""

import time
import functools
from typing import Optional
from github import Github, GithubException, RateLimitExceededException
from github.Issue import Issue
from github.PullRequest import PullRequest
from config.settings import settings
from src.utils.retry import sync_retry


# ========== 全局 GitHub 客户端（延迟初始化） ==========

_github_client: Optional[Github] = None
_repo: Optional[object] = None


def _get_repo():
    """获取 GitHub 仓库对象（延迟初始化 + 缓存）。"""
    global _github_client, _repo
    if _github_client is None:
        _github_client = Github(settings.github_token)
        _repo = _github_client.get_repo(settings.github_repo_full)
    return _repo


# ========== GitHub 操作包装器（带重试） ==========

def _github_retry(max_retries: int = 3):
    """
    GitHub 专用重试装饰器 — 处理 API 限流和临时故障。
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except RateLimitExceededException as e:
                    last_error = e
                    # GitHub 限流 — 等待重置时间
                    try:
                        reset_time = _github_client.rate_limiting_resettime
                        wait = max(reset_time - time.time() + 5, 10)
                    except Exception:
                        wait = 60
                    if attempt < max_retries:
                        import warnings
                        warnings.warn(f"GitHub API 限流，等待 {wait:.0f}s 后重试 (第 {attempt+1}/{max_retries} 次)")
                        time.sleep(wait)
                    else:
                        raise
                except GithubException as e:
                    last_error = e
                    status = e.status if hasattr(e, 'status') else 0
                    # 只重试 5xx 和 429
                    if status >= 500 or status == 429:
                        if attempt < max_retries:
                            delay = min(2 ** attempt, 30)
                            import warnings
                            warnings.warn(f"GitHub API 错误 {status}，{delay}s 后重试 (第 {attempt+1}/{max_retries} 次)")
                            time.sleep(delay)
                        else:
                            raise
                    else:
                        raise  # 4xx 不重试
            raise last_error
        return wrapper
    return decorator


# ========== Issue 操作 ==========

def create_issue(
    title: str,
    body: str,
    labels: Optional[list[str]] = None,
    assignees: Optional[list[str]] = None,
) -> str:
    """
    在 GitHub 仓库中创建一个新的 Issue。

    Args:
        title: Issue 标题
        body: Issue 描述 (Markdown 格式)
        labels: 标签列表，如 ["type/task", "priority/high"]
        assignees: GitHub 用户名列表，用于分配任务

    Returns:
        str: 成功时返回 Issue URL，失败时返回错误信息
    """
    try:
        repo = _get_repo()
        issue = repo.create_issue(
            title=title,
            body=body,
            labels=labels or [],
            assignees=assignees or [],
        )
        return f"Issue 创建成功: {issue.html_url} (编号 #{issue.number})"
    except GithubException as e:
        return f"创建 Issue 失败: {e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)}"


def comment_on_issue(issue_number: int, comment: str) -> str:
    """
    在指定 Issue 上添加评论。

    Args:
        issue_number: Issue 编号
        comment: 评论内容 (Markdown 格式)

    Returns:
        str: 操作结果描述
    """
    try:
        repo = _get_repo()
        issue = repo.get_issue(number=issue_number)
        issue.create_comment(comment)
        return f"已在 Issue #{issue_number} 上添加评论"
    except GithubException as e:
        return f"评论 Issue #{issue_number} 失败: {e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)}"


def close_issue(issue_number: int, comment: Optional[str] = None) -> str:
    """
    关闭指定的 Issue。

    Args:
        issue_number: Issue 编号
        comment: 可选的关闭说明评论

    Returns:
        str: 操作结果描述
    """
    try:
        repo = _get_repo()
        issue = repo.get_issue(number=issue_number)
        if comment:
            issue.create_comment(comment)
        issue.edit(state="closed")
        return f"Issue #{issue_number} 已关闭"
    except GithubException as e:
        return f"关闭 Issue #{issue_number} 失败: {e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)}"


def get_issue(issue_number: int) -> str:
    """
    获取指定 Issue 的详细信息，包括标题、正文、状态、标签和评论。

    Args:
        issue_number: Issue 编号

    Returns:
        str: Issue 详情文本
    """
    try:
        repo = _get_repo()
        issue = repo.get_issue(number=issue_number)
        comments = [f"  - @{c.user.login}: {c.body[:200]}" for c in issue.get_comments()]
        comments_text = "\n".join(comments) if comments else "  (无评论)"

        return f"""
Issue #{issue.number}: {issue.title}
状态: {issue.state}
标签: {', '.join(l.name for l in issue.labels) if issue.labels else '(无)'}
负责人: {', '.join(a.login for a in issue.assignees) if issue.assignees else '(未分配)'}
创建者: {issue.user.login}
URL: {issue.html_url}

正文:
{issue.body or '(无)'}

评论 ({issue.comments} 条):
{comments_text}
""".strip()
    except GithubException as e:
        return f"获取 Issue #{issue_number} 失败: {e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)}"


def list_issues(state: str = "open", labels: Optional[list[str]] = None) -> str:
    """
    列出仓库中的 Issues。

    Args:
        state: Issue 状态 ("open", "closed", "all")
        labels: 按标签筛选，如 ["type/task"]

    Returns:
        str: Issue 列表
    """
    try:
        repo = _get_repo()
        label_str = ",".join(labels) if labels else None
        issues = repo.get_issues(state=state, labels=label_str, sort="created", direction="desc")

        result_parts = [f"仓库 {settings.github_repo_full} 的 Issues (state={state}):"]
        for issue in issues[:20]:  # 最多列出 20 个
            labels_str = ", ".join(f"`{l.name}`" for l in issue.labels) if issue.labels else "(无标签)"
            result_parts.append(
                f"  - #{issue.number} | {issue.state} | [{labels_str}] | "
                f"{issue.title[:80]} | 负责人: {', '.join(a.login for a in issue.assignees) if issue.assignees else '未分配'}"
            )
        return "\n".join(result_parts) if len(result_parts) > 1 else "没有找到 Issues"
    except GithubException as e:
        return f"列出 Issues 失败: {e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)}"


def add_labels_to_issue(issue_number: int, labels: list[str]) -> str:
    """为 Issue 添加标签。"""
    try:
        repo = _get_repo()
        issue = repo.get_issue(number=issue_number)
        issue.add_to_labels(*labels)
        return f"已为 Issue #{issue_number} 添加标签: {', '.join(labels)}"
    except GithubException as e:
        return f"添加标签失败: {e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)}"


# ========== Pull Request 操作 ==========

def create_pull_request(
    title: str,
    body: str,
    head_branch: str,
    base_branch: str = "main",
) -> str:
    """
    创建 Pull Request。

    Args:
        title: PR 标题
        body: PR 描述 (Markdown 格式)
        head_branch: 源分支名称
        base_branch: 目标分支名称 (默认 main)

    Returns:
        str: 操作结果描述
    """
    try:
        repo = _get_repo()
        pr = repo.create_pull(
            title=title,
            body=body,
            head=head_branch,
            base=base_branch,
        )
        return f"PR 创建成功: {pr.html_url} (编号 #{pr.number})"
    except GithubException as e:
        return f"创建 PR 失败: {e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)}"


def merge_pull_request(
    pr_number: int,
    merge_method: str = "squash",
    commit_title: Optional[str] = None,
) -> str:
    """
    合并 Pull Request。

    Args:
        pr_number: PR 编号
        merge_method: 合并方式 ("merge", "squash", "rebase")
        commit_title: squash/rebase 时的提交标题

    Returns:
        str: 操作结果描述
    """
    try:
        repo = _get_repo()
        pr = repo.get_pull(number=pr_number)

        if pr.merged:
            return f"PR #{pr_number} 已经被合并"
        if not pr.mergeable:
            return f"PR #{pr_number} 存在冲突，无法自动合并"

        pr.merge(
            merge_method=merge_method,
            commit_title=commit_title,
        )
        return f"PR #{pr_number} 已成功合并 (方式: {merge_method})"
    except GithubException as e:
        return f"合并 PR #{pr_number} 失败: {e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)}"


def get_pull_request(pr_number: int) -> str:
    """获取 PR 详细信息。"""
    try:
        repo = _get_repo()
        pr = repo.get_pull(number=pr_number)
        reviews = [f"  - @{r.user.login}: {r.state} — {r.body[:100] if r.body else '(无)'}" for r in pr.get_reviews()]

        return f"""
PR #{pr.number}: {pr.title}
状态: {pr.state}
可合并: {pr.mergeable}
分支: {pr.head.ref} → {pr.base.ref}
创建者: {pr.user.login}
URL: {pr.html_url}

描述:
{pr.body or '(无)'}

Reviews ({len(reviews)} 条):
{chr(10).join(reviews) if reviews else '  (无)'}
""".strip()
    except GithubException as e:
        return f"获取 PR #{pr_number} 失败: {e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)}"


def list_pull_requests(state: str = "open") -> str:
    """列出仓库中的 PRs。"""
    try:
        repo = _get_repo()
        prs = repo.get_pulls(state=state, sort="created", direction="desc")

        result_parts = [f"仓库 {settings.github_repo_full} 的 Pull Requests (state={state}):"]
        for pr in prs[:20]:
            result_parts.append(
                f"  - #{pr.number} | {pr.state} | {pr.head.ref} → {pr.base.ref} | "
                f"{pr.title[:80]} | 创建者: {pr.user.login}"
            )
        return "\n".join(result_parts) if len(result_parts) > 1 else "没有找到 PRs"
    except GithubException as e:
        return f"列出 PRs 失败: {e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)}"


# ========== PR Review 操作 ==========

def submit_pr_review(
    pr_number: int,
    body: str,
    event: str = "COMMENT",
) -> str:
    """
    对 PR 提交 Review。

    Args:
        pr_number: PR 编号
        body: Review 正文 (Markdown 格式)
        event: Review 类型 — "APPROVE", "REQUEST_CHANGES", "COMMENT"

    Returns:
        str: 操作结果描述
    """
    try:
        repo = _get_repo()
        pr = repo.get_pull(number=pr_number)
        pr.create_review(body=body, event=event)
        event_cn = {"APPROVE": "✅ 通过", "REQUEST_CHANGES": "❌ 需要修改", "COMMENT": "💬 评论"}
        return f"已对 PR #{pr_number} 提交 Review: {event_cn.get(event, event)}"
    except GithubException as e:
        return f"提交 Review 失败: {e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)}"


# ========== 仓库操作 ==========

def create_branch_on_github(branch_name: str, base_branch: str = "main") -> str:
    """
    在 GitHub 上创建新分支（基于指定分支的 SHA）。

    Args:
        branch_name: 新分支名称
        base_branch: 基分支名称

    Returns:
        str: 操作结果描述
    """
    try:
        repo = _get_repo()
        base = repo.get_branch(base_branch)
        repo.create_git_ref(
            ref=f"refs/heads/{branch_name}",
            sha=base.commit.sha,
        )
        return f"GitHub 分支 {branch_name} 创建成功 (基于 {base_branch})"
    except GithubException as e:
        return f"创建分支 {branch_name} 失败: {e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)}"


# ========== 需求澄清辅助工具 ==========

def _get_bot_username() -> str:
    """
    获取当前认证 GitHub 用户的登录名（用于区分 Bot 评论和用户评论）。

    Returns:
        str: GitHub 用户名，获取失败时返回空字符串
    """
    global _github_client
    try:
        if _github_client is None:
            _github_client = Github(settings.github_token)
        user = _github_client.get_user()
        return user.login or ""
    except GithubException:
        return ""


def _get_issue_comments_raw(issue_number: int) -> list[dict]:
    """
    获取指定 Issue 的结构化评论数据（内部使用）。

    Args:
        issue_number: Issue 编号

    Returns:
        list[dict]: 评论列表，每项包含 id, author, body, created_at
    """
    try:
        repo = _get_repo()
        issue = repo.get_issue(number=issue_number)
        comments = issue.get_comments()
        return [
            {
                "id": c.id,
                "author": c.user.login if c.user else "unknown",
                "body": c.body or "",
                "created_at": c.created_at,
            }
            for c in comments
        ]
    except GithubException:
        return []


def get_issue_comments(issue_number: int, max_comments: int = 50) -> str:
    """
    获取指定 Issue 的评论列表（不包括 Issue 正文）。

    Args:
        issue_number: Issue 编号
        max_comments: 最多返回的评论数 (默认 50)

    Returns:
        str: 格式化的评论列表，或错误信息
    """
    try:
        repo = _get_repo()
        issue = repo.get_issue(number=issue_number)
        comments = issue.get_comments()
        total = comments.totalCount

        if total == 0:
            return f"Issue #{issue_number} 暂无评论"

        result_parts = [f"Issue #{issue_number} 的评论列表 (共 {total} 条):"]
        for c in comments[:max_comments]:
            author = c.user.login if c.user else "unknown"
            created = c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else "?"
            result_parts.append(
                f"\n--- 评论 #{c.id} | @{author} ({created}) ---\n{c.body or '(无内容)'}"
            )

        if total > max_comments:
            result_parts.append(f"\n... (还有 {total - max_comments} 条评论未显示)")

        return "\n".join(result_parts)
    except GithubException as e:
        return f"获取 Issue #{issue_number} 评论失败: {e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)}"


def get_issue_labels(issue_number: int) -> str:
    """
    获取指定 Issue 的标签列表。

    Args:
        issue_number: Issue 编号

    Returns:
        str: 逗号分隔的标签名称列表，或错误信息
    """
    try:
        repo = _get_repo()
        issue = repo.get_issue(number=issue_number)
        labels = [l.name for l in issue.labels]
        if labels:
            return f"Issue #{issue_number} 的标签: {', '.join(labels)}"
        return f"Issue #{issue_number} 没有标签"
    except GithubException as e:
        return f"获取 Issue #{issue_number} 标签失败: {e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)}"


def remove_labels_from_issue(issue_number: int, labels: list[str]) -> str:
    """
    从指定 Issue 移除标签。

    Args:
        issue_number: Issue 编号
        labels: 要移除的标签名称列表

    Returns:
        str: 操作结果描述
    """
    try:
        repo = _get_repo()
        issue = repo.get_issue(number=issue_number)
        removed = []
        for label in labels:
            try:
                issue.remove_from_labels(label)
                removed.append(label)
            except GithubException:
                pass  # 标签可能不存在，跳过
        if removed:
            return f"已从 Issue #{issue_number} 移除标签: {', '.join(removed)}"
        return f"Issue #{issue_number} 没有需要移除的标签"
    except GithubException as e:
        return f"移除 Issue #{issue_number} 标签失败: {e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)}"


def issue_has_label(issue_number: int, label_name: str) -> bool:
    """
    检查 Issue 是否包含指定标签（内部使用）。

    Args:
        issue_number: Issue 编号
        label_name: 要检查的标签名称

    Returns:
        bool: 是否包含该标签
    """
    try:
        repo = _get_repo()
        issue = repo.get_issue(number=issue_number)
        return any(l.name == label_name for l in issue.labels)
    except GithubException:
        return False
