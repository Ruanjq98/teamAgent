"""
文件操作工具集 — 封装本地文件系统操作，作为 AutoGen Agent 可调用的工具函数。

所有路径操作限定在工作目录范围内，确保安全性。
"""

import os
from typing import Optional
from config.settings import settings


def _get_repo_path() -> str:
    """获取仓库本地路径。"""
    return os.path.join(settings.workspace_dir, settings.github_repo_name)


def _safe_path(relative_path: str) -> str:
    """
    将相对路径转换为绝对路径，并确保路径在工作目录内。

    Args:
        relative_path: 相对于仓库根目录的路径

    Returns:
        str: 安全的绝对路径

    Raises:
        ValueError: 路径超出工作目录范围
    """
    repo_path = os.path.abspath(_get_repo_path())
    target_path = os.path.abspath(os.path.join(repo_path, relative_path))

    if not target_path.startswith(repo_path):
        raise ValueError(f"路径越界: {relative_path} (超出仓库范围)")

    return target_path


def read_file(file_path: str, encoding: str = "utf-8") -> str:
    """
    读取仓库中的文件内容。

    Args:
        file_path: 相对于仓库根目录的文件路径
        encoding: 文件编码 (默认 utf-8)

    Returns:
        str: 文件内容，或错误信息
    """
    try:
        target = _safe_path(file_path)
        if not os.path.exists(target):
            return f"文件不存在: {file_path}"
        if os.path.isdir(target):
            return f"路径是目录而非文件: {file_path}"

        with open(target, "r", encoding=encoding) as f:
            content = f.read()

        # 添加行号便于引用
        lines = content.split("\n")
        numbered = "\n".join(f"{i+1:4d}| {line}" for i, line in enumerate(lines))
        return f"文件: {file_path} ({len(lines)} 行)\n{numbered}"
    except ValueError as e:
        return f"路径错误: {str(e)}"
    except Exception as e:
        return f"读取文件失败: {str(e)}"


def write_file(file_path: str, content: str, encoding: str = "utf-8") -> str:
    """
    创建或覆盖写入文件。

    Args:
        file_path: 相对于仓库根目录的文件路径
        content: 文件内容
        encoding: 文件编码 (默认 utf-8)

    Returns:
        str: 操作结果描述

    Notes:
        - 如果父目录不存在，会自动创建
        - 如果文件已存在，会被覆盖
    """
    try:
        target = _safe_path(file_path)

        # 确保父目录存在
        os.makedirs(os.path.dirname(target), exist_ok=True)

        with open(target, "w", encoding=encoding) as f:
            f.write(content)

        # 统计信息
        lines = content.count("\n") + 1
        size = len(content.encode(encoding))
        return f"文件写入成功: {file_path} ({lines} 行, {size} bytes)"
    except ValueError as e:
        return f"路径错误: {str(e)}"
    except Exception as e:
        return f"写入文件失败: {str(e)}"


def delete_file(file_path: str) -> str:
    """
    删除仓库中的文件。

    Args:
        file_path: 相对于仓库根目录的文件路径

    Returns:
        str: 操作结果描述
    """
    try:
        target = _safe_path(file_path)
        if not os.path.exists(target):
            return f"文件不存在: {file_path}"

        os.remove(target)
        return f"文件已删除: {file_path}"
    except ValueError as e:
        return f"路径错误: {str(e)}"
    except Exception as e:
        return f"删除文件失败: {str(e)}"


def list_files(directory: str = ".", recursive: bool = True, max_depth: int = 3) -> str:
    """
    列出目录中的文件。

    Args:
        directory: 相对于仓库根目录的目录路径 (默认仓库根目录)
        recursive: 是否递归列出子目录
        max_depth: 最大递归深度 (默认 3)

    Returns:
        str: 文件列表
    """
    try:
        target = _safe_path(directory)
        if not os.path.exists(target):
            return f"目录不存在: {directory}"
        if not os.path.isdir(target):
            return f"路径不是目录: {directory}"

        result_parts = [f"目录: {directory or '.'}"]
        _list_recursive(target, target, result_parts, recursive, max_depth, current_depth=0)
        return "\n".join(result_parts)
    except ValueError as e:
        return f"路径错误: {str(e)}"
    except Exception as e:
        return f"列出文件失败: {str(e)}"


def _list_recursive(root: str, current: str, result: list, recursive: bool, max_depth: int, current_depth: int):
    """递归列出文件（内部辅助函数）。"""
    if max_depth is not None and current_depth > max_depth:
        return

    try:
        entries = sorted(os.listdir(current))
    except PermissionError:
        return

    for entry in entries:
        full_path = os.path.join(current, entry)
        rel_path = os.path.relpath(full_path, root)

        # 跳过隐藏目录和虚拟环境
        if entry.startswith(".") and entry not in (".gitignore", ".env", ".env.template"):
            continue
        if entry in ("__pycache__", "node_modules", ".git"):
            continue

        prefix = "  " * current_depth
        if os.path.isdir(full_path):
            result.append(f"{prefix}📁 {entry}/")
            if recursive:
                _list_recursive(root, full_path, result, recursive, max_depth, current_depth + 1)
        else:
            size = os.path.getsize(full_path)
            result.append(f"{prefix}📄 {entry} ({_format_size(size)})")


def _format_size(size: int) -> str:
    """格式化文件大小。"""
    for unit in ["B", "KB", "MB"]:
        if size < 1024:
            return f"{size}{unit}"
        size //= 1024
    return f"{size}GB"


def run_command(command: str, timeout: int = 60) -> str:
    """
    在工作目录中执行 Shell 命令。

    Args:
        command: 要执行的命令
        timeout: 超时秒数 (默认 60)

    Returns:
        str: 命令输出 (stdout + stderr)
    """
    import subprocess

    try:
        repo_path = _get_repo_path()
        result = subprocess.run(
            command,
            shell=True,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout.strip()
        if result.stderr.strip():
            output += "\n[stderr]\n" + result.stderr.strip()
        return output or f"命令执行完毕 (exit code: {result.returncode})"
    except subprocess.TimeoutExpired:
        return f"命令超时 ({timeout}s): {command}"
    except Exception as e:
        return f"命令执行失败: {str(e)}"
