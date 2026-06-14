"""
teamAgent — 基于 AutoGen 的多 Agent 项目开发团队

入口模块。支持:
- 单任务执行: python main.py "任务描述"
- 文件输入:   python main.py --file 任务.txt
- 多任务并发: python main.py --batch 任务1.txt 任务2.txt
- 交互模式:   python main.py --interactive
- 角色配置:   python main.py --config custom_roles.yaml "任务描述"
- 模型切换:   python main.py --backend ollama "任务描述"

用法:
    python main.py "创建一个 Python Web API 项目"
    python main.py --interactive
"""

import asyncio
import os
import sys

# 修复 Windows GBK 终端 Unicode 输出问题（务必在最前面设置）
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from loguru import logger

from src.utils.logger import setup_logger
from workflows.pipeline import run_project
from src.utils.reporter import generate_markdown_report, generate_html_report


def print_banner():
    """打印启动横幅。"""
    print("""
+==========================================+
|         teamAgent v0.2.0                 |
|   基于 AutoGen 的自动化开发团队            |
|                                          |
|   角色: 开发经理 | 开发人员 | 测试人员     |
|   通信: GitHub Issues                    |
+==========================================+
    """)


async def run_single(requirement: str, report: bool = True) -> dict:
    """运行单个任务。"""
    summary = await run_project(requirement)
    if report and summary.get("status") == "completed":
        generate_markdown_report(summary, requirement)
    return summary


async def run_batch(files: list[str]):
    """批量并发运行多个任务。"""
    from src.utils.task_queue import TaskQueue

    queue = TaskQueue(max_concurrency=3)

    for f in files:
        with open(f, "r", encoding="utf-8") as fh:
            requirement = fh.read().strip()
        queue.add_task(requirement)

    async def on_done(task):
        logger.info(f"[通知] 任务 {task.task_id} 完成: {task.status}")

    queue.on_complete(on_done)
    results = await queue.run_all()

    for r in results:
        status = r.get("status", "unknown")
        tid = r.get("task_id", "?")
        logger.info(f"  {tid}: {status}")

    return results


async def interactive_mode():
    """交互式模式。"""
    from src.utils.task_queue import TaskQueue

    queue = TaskQueue(max_concurrency=5)

    print("🎛️  交互模式已启动")
    print("命令: add <任务> | status [task_id] | run | quit\n")

    while True:
        try:
            cmd = input("teamAgent> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not cmd:
            continue
        elif cmd.lower() == "quit" or cmd.lower() == "exit":
            print("再见！")
            break
        elif cmd.lower() == "run":
            print("启动所有排队任务...")
            results = await queue.run_all()
            for r in results:
                print(f"  {r['task_id']}: {r['status']}")
        elif cmd.lower().startswith("status"):
            parts = cmd.split(maxsplit=1)
            tid = parts[1] if len(parts) > 1 else None
            status = queue.get_status(tid)
            if tid:
                print(f"  任务 {tid}: {status.get('status', '?')}")
            else:
                s = status
                print(f"  总计: {s['total']} | 排队: {s['queued']} | 运行: {s['running']} | 完成: {s['completed']} | 失败: {s['failed']}")
        elif cmd.lower().startswith("add "):
            requirement = cmd[4:].strip()
            tid = queue.add_task(requirement)
            print(f"  已添加任务: {tid}")
        else:
            print(f"  未知命令: {cmd}")
            print("  可用命令: add <任务> | status | run | quit")


async def main():
    """程序主入口。"""
    print_banner()
    setup_logger()

    # 解析命令行参数
    args = sys.argv[1:]

    if not args:
        print("用法:")
        print("  python main.py <任务描述>")
        print("  python main.py --file 任务.txt")
        print("  python main.py --batch 任务1.txt 任务2.txt")
        print("  python main.py --interactive")
        print("  python main.py --backend ollama <任务描述>")
        print("  python main.py --config custom.yaml <任务描述>")
        sys.exit(1)

    # --interactive
    if "--interactive" in args or "-i" in args:
        await interactive_mode()
        return

    # --batch
    if "--batch" in args:
        idx = args.index("--batch")
        files = args[idx + 1:]
        if not files:
            print("错误: --batch 需要指定至少一个文件")
            sys.exit(1)
        await run_batch(files)
        return

    # --file
    if "--file" in args:
        idx = args.index("--file")
        if idx + 1 >= len(args):
            print("错误: --file 需要指定文件路径")
            sys.exit(1)
        filepath = args[idx + 1]
    else:
        filepath = None

    # 解析需求
    if filepath:
        with open(filepath, "r", encoding="utf-8") as f:
            requirement = f.read().strip()
        logger.info(f"从文件加载需求: {filepath}")
    else:
        # 过滤掉 --xxx 选项，其余作为需求
        requirement_parts = [a for a in args if not a.startswith("--")]
        requirement = " ".join(requirement_parts)

    if not requirement:
        print("错误: 任务描述不能为空")
        sys.exit(1)

    logger.info("=" * 50)
    logger.info("开始执行项目")
    logger.info(f"需求: {requirement[:200]}...")
    logger.info("=" * 50)

    try:
        summary = await run_single(requirement, report=True)

        logger.info("\n" + "=" * 50)
        logger.info("📊 执行摘要")
        logger.info(f"  状态: {summary.get('status', 'unknown')}")
        logger.info(f"  迭代: {summary.get('total_iterations', 0)} 轮")
        logger.info(f"  耗时: {summary.get('elapsed_time', 'N/A')}")
        logger.info("=" * 50)

    except KeyboardInterrupt:
        logger.warning("⏹️ 用户中断执行")
    except Exception as e:
        logger.error(f"❌ 执行失败: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
