import sys
import subprocess
from pathlib import Path
from typing import Any, Optional, Dict, Tuple, Set
from urllib.parse import urlparse, unquote
import typer
from jinja2 import Environment, meta

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

def resolve_dynamic_values(context: Dict[str, Any], repo_root: Optional[Path], dependencies_to_process: Set[str]) -> Tuple[Dict[str, Any], Set[str]]:
    """
    解析以 '$' 开头的配置值，将其作为 Jinja2 模板进行渲染。
    此函数只处理 `dependencies_to_process` 中指定的顶层键，以避免不必要的副作用。
    渲染后的结果会被再次处理，以支持 `$!` 和 `$@` 语法。
    同时，它会收集在这些模板中发现的所有变量依赖。
    """
    env = Environment(autoescape=False)
    discovered_dependencies = set()

    def resolve_node(node: Any, key_path: str) -> Any:
        """递归处理一个节点 (字典或值)"""
        if isinstance(node, dict):
            # 递归处理字典的每个值
            return {k: resolve_node(v, f"{key_path}.{k}") for k, v in node.items()}
        
        if not isinstance(node, str):
            return node

        if node.startswith('$'):
            template_src = node[1:]
            try:
                ast = env.parse(template_src)
                discovered_dependencies.update(meta.find_undeclared_variables(ast))
            except Exception:
                pass

            try:
                rendered = env.from_string(template_src).render(context)
                final_value = process_value(key_path, rendered, repo_root)
                return final_value
            except Exception as e:
                rich_echo(f"  [警告] 动态解析变量 '{key_path}' 失败: {e}", fg=typer.colors.YELLOW)
                return node # Return original value on failure
        
        # 处理普通的 @ 和 ! (不带 $ 前缀的)
        return process_value(key_path, node, repo_root)

    # 只迭代需要处理的顶层依赖项
    for key in dependencies_to_process:
        if key in context:
            context[key] = resolve_node(context[key], key)

    return context, discovered_dependencies