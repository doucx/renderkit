import sys
import yaml
import typer
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse, unquote

from jinja2 import Environment, FileSystemLoader, BaseLoader

# --- Constants ---
CONFIGS_DIR_NAME = "configs"
TEMPLATES_DIR_NAME = "templates"
OUTPUTS_DIR_NAME = "outputs"
GLOBAL_CONFIG_FILENAME = "config.yaml"

# --- Typer App Initialization ---
app = typer.Typer(
    help="一个强大的、由配置驱动的 Jinja2 模板渲染工具，支持分层配置和多种输入/输出模式。",
    add_completion=False,
    rich_markup_mode="markdown"
)

# --- State Management ---
# Using a simple class to hold global state like 'quiet mode' to avoid global variables.
class State:
    quiet = False

state = State()

def rich_echo(message: str, **kwargs):
    """A wrapper around typer.echo that respects the quiet flag."""
    if not state.quiet:
        typer.secho(message, **kwargs)

# --- Core Helper Functions ---

def deep_merge_dicts(source: dict, destination: dict) -> dict:
    """
    深度合并两个字典。'source' 中的值会覆盖 'destination' 中的值。
    """
    for key, value in source.items():
        if isinstance(value, dict) and key in destination and isinstance(destination[key], dict):
            destination[key] = deep_merge_dicts(value, destination[key])
        else:
            destination[key] = value
    return destination

def set_nested_key(d: dict, key_path: str, value: Any):
    """
    通过点分隔的路径 (e.g., 'KOS.version') 在嵌套字典中设置值。
    """
    keys = key_path.split('.')
    current_level = d
    for i, key in enumerate(keys[:-1]):
        current_level = current_level.setdefault(key, {})
        if not isinstance(current_level, dict):
            rich_echo(f"[错误] 在设置 '{key_path}' 时，路径中的 '{key}' 不是一个字典。", fg=typer.colors.RED)
            return
    current_level[keys[-1]] = value

def process_value(key: str, value: Any, repo_root: Optional[Path]) -> Any:
    """处理配置文件中的特殊值 (@, file://, !)."""
    if not isinstance(value, str):
        return value

    file_path_to_read = None

    # --- 方案 1: 处理 file:// URI ---
    if value.startswith('file://'):
        parsed_uri = urlparse(value)
        # urllib.parse 的行为可能令人困惑，我们在此明确处理。
        # 对于 'file://path/to/file', netloc 是 'path', path 是 '/to/file'。
        # 对于 'file:///path/to/file', netloc 是 '', path 是 '/path/to/file'。
        # 对于 'file://./relative', netloc 是 '.', path 是 '/relative'。
        # 我们需要正确地重建路径。
        path_str = unquote(parsed_uri.netloc + parsed_uri.path)

        # Windows 路径修正: urlparse 可能会给 'C:\...' 加上一个前导 '/'
        if sys.platform == "win32" and path_str.startswith('/') and ":" in path_str:
            path_str = path_str[1:]
        
        path_obj = Path(path_str)

        # 关键修复:
        # 如果解析出的路径不是绝对路径，就根据当前工作目录解析它。
        if not path_obj.is_absolute():
            file_path_to_read = Path.cwd() / path_obj
        else:
            file_path_to_read = path_obj

    # --- 方案 2: 处理 @ 相对路径 ---
    elif value.startswith('@'):
        relative_path_str = value[1:].lstrip('/')
        if not repo_root:
            rich_echo(f"  [警告] 变量 '{key}' 的 @ 路径 '{value[1:]}' 无法解析：'repo_root' 未定义。", fg=typer.colors.YELLOW)
            return f"<渲染错误: repo_root未定义>"
        file_path_to_read = repo_root / relative_path_str

    # --- 如果确定了要读取的文件路径 ---
    if file_path_to_read:
        # 解析路径以获得清晰的绝对路径，用于错误信息。
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

    # --- 处理命令执行: !command ---
    if value.startswith('!'):
        # (这部分逻辑不变)
        command = value[1:]
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, check=True, encoding='utf-8')
            return result.stdout.strip()
        except Exception as e:
            rich_echo(f"  [错误] 执行命令 '{command}' (来自变量 '{key}') 失败: {e}", fg=typer.colors.RED)
            return f"<渲染错误: 命令执行失败>"

    return value

def load_and_process_configs(
    project_root: Path,
    no_project_config: bool,
    global_config_paths: List[Path],
    config_paths: List[Path],
    repo_root_override: Optional[Path],
    set_vars: List[str]
) -> Dict[str, Any]:
    """
    根据优先级瀑布流加载、合并和处理所有配置。
    """
    rich_echo("--- 1. 加载配置 ---", bold=True)
    
    global_context = {}
    namespaced_contexts = {}

    # 1. 基础层: 项目配置
    if not no_project_config:
        rich_echo(f"  正在加载项目配置: {project_root}")
        # a) 加载全局 config.yaml
        global_config_file = project_root / GLOBAL_CONFIG_FILENAME
        if global_config_file.is_file():
            global_context = yaml.safe_load(global_config_file.read_text('utf-8')) or {}
        
        # b) 加载 configs/ 目录下的命名空间配置
        configs_dir = project_root / CONFIGS_DIR_NAME
        if configs_dir.is_dir():
            for config_file in configs_dir.glob('*.yaml'):
                parts = config_file.stem.split('-', 1)
                if len(parts) > 0:
                    prefix = parts[0]
                    content = yaml.safe_load(config_file.read_text('utf-8')) or []
                    namespaced_contexts.setdefault(prefix, {})
                    for item in content:
                        if isinstance(item, dict) and len(item) == 1:
                            key, value = next(iter(item.items()))
                            namespaced_contexts[prefix][key] = value

    # 2. 文件覆盖层: -g 和 -c
    for g_path in global_config_paths:
        rich_echo(f"  正在应用全局配置文件 (-g): {g_path}")
        override_globals = yaml.safe_load(g_path.read_text('utf-8')) or {}
        global_context = deep_merge_dicts(override_globals, global_context)

    for c_path in config_paths:
        rich_echo(f"  正在应用命名空间配置文件 (-c): {c_path}")
        prefix = c_path.stem.split('-', 1)[0]
        override_ns = yaml.safe_load(c_path.read_text('utf-8')) or []
        
        current_ns_context = namespaced_contexts.setdefault(prefix, {})
        override_ns_dict = {}
        for item in override_ns:
            if isinstance(item, dict) and len(item) == 1:
                key, value = next(iter(item.items()))
                override_ns_dict[key] = value
        
        namespaced_contexts[prefix] = deep_merge_dicts(override_ns_dict, current_ns_context)

    # --- 组合最终上下文 ---
    final_context = {**global_context, **namespaced_contexts}
    
    # 3. 特定参数覆盖层: -r
    if repo_root_override:
        rich_echo(f"  正在应用 repo_root 覆盖 (-r): {repo_root_override}")
        final_context['repo_root'] = str(repo_root_override)

    # --- 解析 repo_root ---
    repo_root = None
    if 'repo_root' in final_context:
        repo_root = Path(final_context['repo_root']).expanduser()
        if not repo_root.is_dir():
            rich_echo(f"  [警告] 'repo_root' 指向的路径不是有效目录: {repo_root}", fg=typer.colors.YELLOW)
            repo_root = None
    
    # --- 值处理阶段 ---
    rich_echo("--- 2. 处理变量值 (@, !) ---", bold=True)
    processed_context = {}
    for key, value in final_context.items():
        if isinstance(value, dict): # 命名空间
            processed_context[key] = {}
            for ns_key, ns_value in value.items():
                processed_context[key][ns_key] = process_value(f"{key}.{ns_key}", ns_value, repo_root)
        else: # 全局变量
             processed_context[key] = process_value(key, value, repo_root)
    
    # 4. 最终覆盖层: --set
    if set_vars:
        rich_echo("--- 3. 应用 --set 变量 ---", bold=True)
        for var in set_vars:
            if '=' not in var:
                rich_echo(f"  [警告] --set 参数格式无效，已跳过: '{var}'", fg=typer.colors.YELLOW)
                continue
            key_path, value_str = var.split('=', 1)
            # 先对值进行处理，使其也支持 @ 和 !
            processed_value = process_value(key_path, value_str, repo_root)
            set_nested_key(processed_context, key_path, processed_value)
            rich_echo(f"  - {key_path} => (processed value)")

    return processed_context


@app.command()
def render(
    template_path: Optional[Path] = typer.Option(
        None, "-t", "--template",
        help="要渲染的单个模板文件路径。如果提供，输出到 stdout。",
        exists=True, file_okay=True, dir_okay=False, readable=True,
    ),
    directory: Optional[Path] = typer.Option(
        None, "-d", "--directory",
        help="指定项目根目录，用于加载基础配置。默认为脚本所在目录。",
        exists=True, file_okay=False, dir_okay=True, readable=True,
    ),
    no_project_config: bool = typer.Option(
        False, "--no-project-config",
        help="禁用基础项目配置的加载 (config.yaml, configs/)。",
    ),
    global_config_paths: Optional[List[Path]] = typer.Option(
        None, "-g", "--global-config",
        help="指定全局配置文件进行覆盖或添加 (可多次使用)。",
        exists=True, file_okay=True, dir_okay=False, readable=True,
    ),
    config_paths: Optional[List[Path]] = typer.Option(
        None, "-c", "--config",
        help="指定命名空间配置文件进行覆盖或添加 (可多次使用)。",
        exists=True, file_okay=True, dir_okay=False, readable=True,
    ),
    repo_root_override: Optional[Path] = typer.Option(
        None, "-r", "--repo-root",
        help="强制指定 repo_root，覆盖任何配置文件中的设置。",
        exists=True, file_okay=False, dir_okay=True, readable=True, resolve_path=True,
    ),
    set_vars: Optional[List[str]] = typer.Option(
        None, "--set",
        help="以 'KEY=VALUE' 或 'NAMESPACE.KEY=VALUE' 格式设置变量，拥有最高优先级 (可多次使用)。"
    ),
    scope: Optional[str] = typer.Option(
        None, "-s", "--scope",
        help="为单个模板提供默认作用域，使其可以直接访问该命名空间下的变量。"
    ),
    quiet: bool = typer.Option(
        False, "-q", "--quiet",
        help="安静模式，只输出最终结果 (stdout模式) 或错误信息。"
    ),
):
    """
    渲染 Jinja2 模板，支持分层配置和多种输入/输出模式。
    """
    state.quiet = quiet
    
    # --- 确定模板源和输出目标 ---
    stdin_content = None
    if not sys.stdin.isatty():
        if template_path:
            rich_echo("[错误] 不能同时从 stdin 和 -t/--template 提供模板。", fg=typer.colors.RED)
            raise typer.Exit(1)
        stdin_content = sys.stdin.read()

    # --- 确定项目根目录 ---
    project_root = (directory or Path(__file__).parent).resolve()

    # --- 加载所有配置 ---
    context = load_and_process_configs(
        project_root,
        no_project_config,
        global_config_paths or [],
        config_paths or [],
        repo_root_override,
        set_vars or []
    )

    # --- 创建 Jinja2 环境 ---
    # 对于 Markdown/代码模板，通常不需要自动转义
    env = Environment(autoescape=False, trim_blocks=True, lstrip_blocks=True)
    
    rich_echo("--- 4. 开始渲染 ---", bold=True)
    
    # --- 模式一 & 二: Stdin 或 -t 单文件模式 ---
    if stdin_content is not None or template_path:
        template_content = stdin_content if stdin_content is not None else template_path.read_text('utf-8')
        
        render_context = context.copy()
        if scope:
            if scope in render_context and isinstance(render_context[scope], dict):
                rich_echo(f"  应用作用域 (-s): '{scope}'")
                render_context.update(render_context[scope])
            else:
                rich_echo(f"  [警告] 作用域 '{scope}' 在配置中不存在，已忽略。", fg=typer.colors.YELLOW)

        try:
            template = env.from_string(template_content)
            output = template.render(render_context)
            print(output, end='') # 直接输出到 stdout
        except Exception as e:
            rich_echo(f"[错误] 渲染模板失败: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
            
    # --- 模式三: 目录渲染模式 ---
    else:
        templates_dir = project_root / TEMPLATES_DIR_NAME
        outputs_dir = project_root / OUTPUTS_DIR_NAME
        
        if not templates_dir.is_dir():
            rich_echo(f"[错误] 模板目录不存在: {templates_dir}", fg=typer.colors.RED)
            raise typer.Exit(1)
        
        env.loader = FileSystemLoader(templates_dir)
        
        for template_file in templates_dir.glob('**/*'):
            if template_file.is_dir():
                continue

            relative_path = template_file.relative_to(templates_dir)
            rich_echo(f"\n* 正在处理: {relative_path}")
            
            render_context = context.copy()
            # 检查是否在特定前缀的子目录下
            if len(relative_path.parts) > 1:
                dir_scope = relative_path.parts[0]
                if dir_scope in render_context and isinstance(render_context[dir_scope], dict):
                    rich_echo(f"  -> 应用目录作用域: '{dir_scope}'")
                    render_context.update(render_context[dir_scope])
            
            try:
                template = env.get_template(str(relative_path))
                output_content = template.render(render_context)
                
                output_path = outputs_dir / relative_path
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(output_content, encoding='utf-8')
                rich_echo(f"  => 渲染成功: {output_path}", fg=typer.colors.GREEN)
            except Exception as e:
                 rich_echo(f"  [错误] 渲染模板 '{relative_path}' 失败: {e}", fg=typer.colors.RED)

    rich_echo("\n--- ✨ 处理完毕 ---", bold=True, fg=typer.colors.BRIGHT_GREEN)

if __name__ == "__main__":
    app()
