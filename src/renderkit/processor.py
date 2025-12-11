import sys
import subprocess
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, unquote
import typer

from .console import rich_echo

def process_value(key: str, value: Any, repo_root: Optional[Path]) -> Any:
    """处理配置文件中的特殊值 (@, file://, !)."""
    if not isinstance(value, str):
        return value

    file_path_to_read = None

    if value.startswith('file://'):
        parsed_uri = urlparse(value)
        path_str = unquote(parsed_uri.netloc + parsed_uri.path)

        if sys.platform == "win32" and path_str.startswith('/') and ":" in path_str:
            path_str = path_str[1:]
        
        path_obj = Path(path_str)

        if not path_obj.is_absolute():
            file_path_to_read = Path.cwd() / path_obj
        else:
            file_path_to_read = path_obj

    elif value.startswith('@'):
        relative_path_str = value[1:].lstrip('/')
        if not repo_root:
            rich_echo(f"  [警告] 变量 '{key}' 的 @ 路径 '{value[1:]}' 无法解析：'repo_root' 未定义。", fg=typer.colors.YELLOW)
            return f"<渲染错误: repo_root未定义>"
        file_path_to_read = repo_root / relative_path_str

    if file_path_to_read:
        file_path_to_read = file_path_to_read.resolve()
        
        if file_path_to_read.is_file():
            try:
                return file_path_to_read.read_text(encoding='utf-8')
            except Exception as e:
                rich_echo(f"  [错误] 读取文件 '{file_path_to_read}' 失败: {e}", fg=typer.colors.RED)
                return f"<渲染错误: 读取文件失败>"
        else:
            rich_echo(f"  [警告] 引用的文件不存在: {file_path_to_read}", fg=typer.colors.YELLOW)
            return f"<渲染错误: 文件不存在>"

    if value.startswith('!'):
        command = value[1:]
        try:
            exec_cwd = repo_root if (repo_root and repo_root.is_dir()) else None
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True, 
                check=True, 
                encoding='utf-8',
                cwd=exec_cwd
            )
            return result.stdout.strip()
        except Exception as e:
            rich_echo(f"  [错误] 执行命令 '{command}' (来自变量 '{key}') 失败: {e}", fg=typer.colors.RED)
            return f"<渲染错误: 命令执行失败>"

    return value