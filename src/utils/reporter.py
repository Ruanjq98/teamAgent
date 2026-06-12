"""
执行报告生成器 — 每次任务完成后自动生成 Markdown/HTML 格式报告。

P3.5: 支持 Markdown（默认）和 HTML 两种格式。
"""

import os
from datetime import datetime
from typing import Optional
from loguru import logger

REPORT_DIR = "reports"


def _ensure_report_dir():
    os.makedirs(REPORT_DIR, exist_ok=True)


def generate_markdown_report(summary: dict, requirement: str) -> str:
    """
    生成 Markdown 格式的执行报告。

    Args:
        summary: 管道执行摘要
        requirement: 原始需求

    Returns:
        str: 报告文件路径
    """
    _ensure_report_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"report_{timestamp}.md"
    filepath = os.path.join(REPORT_DIR, filename)

    status_icon = {"completed": "✅", "paused": "⏸️", "error": "❌"}
    icon = status_icon.get(summary.get("status", ""), "❓")

    lines = [
        f"# 🤖 teamAgent 执行报告",
        f"",
        f"**生成时间**: {datetime.now().isoformat()}",
        f"**执行状态**: {icon} {summary.get('status', 'unknown')}",
        f"",
        f"---",
        f"",
        f"## 📋 原始需求",
        f"",
        f"> {requirement}",
        f"",
        f"## 📊 执行统计",
        f"",
        f"| 指标 | 值 |",
        f"|---|---|",
        f"| 总迭代次数 | {summary.get('total_iterations', 'N/A')} |",
        f"| 总耗时 | {summary.get('elapsed_time', 'N/A')} |",
    ]

    # 迭代历史
    iter_summary = summary.get("iteration_summary", {})
    if iter_summary and iter_summary.get("history"):
        lines += [
            f"| 最大迭代限制 | {iter_summary.get('max_iterations', 'N/A')} |",
            f"",
            f"## 🔄 迭代历史",
            f"",
        ]
        for h in iter_summary["history"]:
            status = "✅" if h.get("status") == "completed" else "❌"
            lines.append(f"- {status} 第 {h['iter']} 轮: {h['status']}")

    # Issues 和 PRs
    lines += [
        f"",
        f"## 📝 最终 Issues",
        f"",
        f"```",
        summary.get("final_issues", "N/A"),
        f"```",
        f"",
        f"## 🔀 最终 Pull Requests",
        f"",
        f"```",
        summary.get("final_prs", "N/A"),
        f"```",
    ]

    # Cleanup
    cleanup = summary.get("cleanup", "")
    if cleanup:
        lines += [
            f"",
            f"## 🧹 清理",
            f"",
            str(cleanup),
        ]

    lines += [
        f"",
        f"---",
        f"",
        f"*本报告由 teamAgent 自动生成*",
    ]

    content = "\n".join(lines)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"Markdown 报告已生成: {filepath}")
    return filepath


def generate_html_report(summary: dict, requirement: str) -> str:
    """
    生成 HTML 格式的执行报告。

    Args:
        summary: 管道执行摘要
        requirement: 原始需求

    Returns:
        str: 报告文件路径
    """
    _ensure_report_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"report_{timestamp}.html"
    filepath = os.path.join(REPORT_DIR, filename)

    status_color = {"completed": "#28a745", "paused": "#ffc107", "error": "#dc3545"}
    color = status_color.get(summary.get("status", ""), "#6c757d")
    status_icon = {"completed": "✅", "paused": "⏸️", "error": "❌"}
    icon = status_icon.get(summary.get("status", ""), "❓")

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>teamAgent 执行报告</title>
    <style>
        body {{ font-family: -apple-system, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; background: #1e1e1e; color: #d4d4d4; }}
        h1 {{ color: #569cd6; }}
        h2 {{ color: #4ec9b0; border-bottom: 1px solid #333; padding-bottom: 0.3rem; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #333; padding: 0.5rem; text-align: left; }}
        th {{ background: #333; }}
        pre {{ background: #2d2d2d; padding: 1rem; border-radius: 4px; overflow-x: auto; }}
        blockquote {{ border-left: 3px solid #569cd6; margin: 0; padding-left: 1rem; color: #9cdcfe; }}
        .status {{ display: inline-block; padding: 0.2rem 0.6rem; border-radius: 4px; color: white; background: {color}; }}
        .footer {{ color: #666; font-size: 0.8rem; margin-top: 2rem; }}
    </style>
</head>
<body>
    <h1>🤖 teamAgent 执行报告</h1>
    <p><strong>生成时间</strong>: {datetime.now().isoformat()}</p>
    <p><strong>执行状态</strong>: <span class="status">{icon} {summary.get('status', 'unknown')}</span></p>

    <h2>📋 原始需求</h2>
    <blockquote>{requirement}</blockquote>

    <h2>📊 执行统计</h2>
    <table>
        <tr><th>指标</th><th>值</th></tr>
        <tr><td>总迭代次数</td><td>{summary.get('total_iterations', 'N/A')}</td></tr>
        <tr><td>总耗时</td><td>{summary.get('elapsed_time', 'N/A')}</td></tr>
        <tr><td>清理结果</td><td>{summary.get('cleanup', 'N/A')}</td></tr>
    </table>

    <hr class="footer">
    <p class="footer">本报告由 teamAgent 自动生成</p>
</body>
</html>"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"HTML 报告已生成: {filepath}")
    return filepath
