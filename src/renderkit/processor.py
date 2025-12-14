import sys
import subprocess
from pathlib import Path
from typing import Any, Optional, Dict, List
from urllib.parse import urlparse, unquote
from jinja2 import Environment
import typer

from .console import rich_echo, rich_debug
from .utils import set_nested_key
from .graph import Node

def process_value(key: str, value: Any, repo_root: Optional[Path]) -> Any:
    """
    处理特殊值 (@, file://, !).
    此时 value 应当已经是经 Jinja2 渲染后的干净字符串，不应包含 {{ }}.
    """
    if not isinstance(value, str):
        return value

    # 最后的安全防线：绝对禁止执行未渲染的模板
    if "{{" in value or "}}" in value:
        rich_debug(f"[Security] 拦截了包含未解析模板的操作: {key} = {value}")
        return value

    # 1. 处理文件读取 (@, file://)
    file_path_to_read = None
    if value.startswith('file://'):
        parsed_uri = urlparse(value)
        path_str = unquote(parsed_uri.netloc + parsed_uri.path)
        if sys.platform == "win32" and path_str.startswith('/') and ":" in path_str:
            path_str = path_str[1:]
        path_obj = Path(path_str)
        file_path_to_read = path_obj if path_obj.is_absolute() else Path.cwd() / path_obj

    if value.startswith('@'):
        if not repo_root:
            return f"<Error: repo_root undefined>"
        file_path_to_read = (repo_root / value[1:].lstrip('/')).resolve()

    if file_path_to_read:
        rich_debug(f"[Executor] 读取文件: {file_path_to_read}")
        if file_path_to_read.is_file():
            try:
                return file_path_to_read.read_text(encoding='utf-8')
            except Exception as e:
                rich_echo(f"[错误] 读取文件失败: {e}", fg=typer.colors.RED)
                return str(e)
        return f"<Error: File not found {file_path_to_read}>"

    # 2. 处理命令执行 (!)
    if value.startswith('!'):
        command = value[1:]
        rich_debug(f"[Executor] 执行命令: {command}")
        try:
            exec_cwd = repo_root if (repo_root and repo_root.is_dir()) else None
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, check=True, encoding='utf-8', cwd=exec_cwd
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            rich_echo(f"[错误] 命令执行失败 '{command}': {e.stderr}", fg=typer.colors.RED)
            return f"<Error: Command failed>"
        except Exception as e:
            rich_echo(f"[错误] 命令执行异常: {e}", fg=typer.colors.RED)
            return str(e)

    return value

class PlanExecutor:
    def __init__(self, repo_root: Optional[Path]):
        self.repo_root = repo_root
        self.env = Environment(autoescape=False)
        self.final_context: Dict[str, Any] = {}

    def execute(self, plan: List[Node], initial_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        严格按照计划顺序执行。
        """
        self.final_context = initial_context.copy()
        
        rich_debug(f"[Executor] 开始执行计划，共 {len(plan)} 个节点")

        for node in plan:
            value_to_process = node.raw_value

            # --- 阶段 1: 渲染 (如果需要) ---
            # 如果是动态值，先进行 Jinja2 渲染
            if isinstance(value_to_process, str) and value_to_process.startswith('$'):
                template_src = value_to_process[1:]
                
                # 构造渲染上下文：全局上下文 + 命名空间注入
                render_ctx = self.final_context.copy()
                if node.namespace and node.namespace in self.final_context:
                    ns_data = self.final_context[node.namespace]
                    if isinstance(ns_data, dict):
                        render_ctx.update(ns_data)
                
                try:
                    # 渲染
                    value_to_process = self.env.from_string(template_src).render(render_ctx)
                except Exception as e:
                    rich_echo(f"[警告] 渲染变量 '{node.key_path}' 失败: {e}", fg=typer.colors.YELLOW)
                    # 失败时保留原始值（去除 $），方便调试
                    value_to_process = template_src

            # --- 阶段 2: 执行 (如果需要) ---
            # 将渲染后的结果（或原始值）交给 process_value 处理 !, @, file:// 等
            final_val = process_value(node.key_path, value_to_process, self.repo_root)
            
            # --- 阶段 3: 写回上下文 ---
            set_nested_key(self.final_context, node.key_path, final_val)
            
            # 调试日志
            val_preview = str(final_val)
            if len(val_preview) > 50: val_preview = val_preview[:50] + "..."
            rich_debug(f"  -> [{node.key_path}] = {val_preview}")

        return self.final_context