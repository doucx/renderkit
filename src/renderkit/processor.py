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

def resolve_dynamic_values(context: Dict[str, Any], repo_root: Optional[Path]) -> Tuple[Dict[str, Any], Set[str]]:
    """
    解析以 '$' 开头的配置值，将其作为 Jinja2 模板进行渲染。
    渲染后的结果会被再次处理，以支持 `$!` 和 `$@` 语法。
    同时，它会收集在这些模板中发现的所有变量依赖。
    """
    env = Environment(autoescape=False)
    discovered_dependencies = set()
    
    # 递归遍历字典并原地更新
    def walk_and_resolve(d: Dict[str, Any]):
        for k, v in list(d.items()):
            if isinstance(v, dict):
                walk_and_resolve(v)
            elif isinstance(v, str) and v.startswith('$'):
                template_src = v[1:] # 去掉前缀 $
                
                # 发现新的依赖
                try:
                    ast = env.parse(template_src)
                    discovered_dependencies.update(meta.find_undeclared_variables(ast))
                except Exception:
                    pass # 渲染时会报告更详细的错误

                try:
                    # 步骤 1: 使用当前的完整 context 进行渲染
                    rendered = env.from_string(template_src).render(context)
                    
                    # 步骤 2: 将渲染结果再次送入 process_value，以处理 `!` 和 `@`
                    final_value = process_value(k, rendered, repo_root)

                    if final_value != v:
                        d[k] = final_value
                except Exception as e:
                    rich_echo(f"  [警告] 动态解析变量 '{k}' 失败: {e}", fg=typer.colors.YELLOW)
    
    walk_and_resolve(context)
    return context, discovered_dependencies