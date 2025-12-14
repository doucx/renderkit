import sys
import typer
from pathlib import Path
from typing import List, Optional
from jinja2 import Environment, FileSystemLoader, meta

from .console import state, rich_echo, rich_debug
from .config import load_and_process_configs
from .processor import process_value

TEMPLATES_DIR_NAME = "templates"
OUTPUTS_DIR_NAME = "outputs"

app = typer.Typer(
    help="一个强大的、由配置驱动的 Jinja2 模板渲染工具，支持分层配置和多种输入/输出模式。",
    add_completion=False,
    rich_markup_mode="markdown"
)

@app.command()
def render(
    template_path: Optional[Path] = typer.Option(
        None, "-t", "--template",
        help="要渲染的单个模板文件路径。如果提供，输出到 stdout。",
        exists=True, file_okay=True, dir_okay=False, readable=True,
    ),
    directory: Optional[Path] = typer.Option(
        None, "-d", "--directory",
        help="指定项目根目录，用于加载基础配置。默认为当前工作目录。",
        exists=True, file_okay=False, dir_okay=True, readable=True, resolve_path=True,
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
    debug: bool = typer.Option(
        False, "--debug",
        help="启用详细的调试日志，输出到 stderr。"
    ),
):
    """
    渲染 Jinja2 模板，支持分层配置和多种输入/输出模式。
    """
    state.quiet = quiet
    state.debug = debug
    
    stdin_content = None
    if not sys.stdin.isatty():
        content = sys.stdin.read()
        if content:
            stdin_content = content

    if stdin_content is not None and template_path:
        rich_echo("[错误] 不能同时从 stdin 和 -t/--template 提供模板。", fg=typer.colors.RED)
        raise typer.Exit(1)

    project_root = directory if directory else Path.cwd()
    env = Environment(autoescape=False, trim_blocks=True, lstrip_blocks=True)
    
    required_vars = None
    
    if stdin_content is not None or template_path:
        template_content = stdin_content if stdin_content is not None else template_path.read_text('utf-8')
        ast = env.parse(template_content)
        required_vars = meta.find_undeclared_variables(ast)
    else:
        # Directory mode: find all variables from all templates first for efficiency
        templates_dir = project_root / TEMPLATES_DIR_NAME
        if templates_dir.is_dir():
            all_vars = set()
            for template_file in templates_dir.glob('**/*'):
                if template_file.is_file():
                    try:
                        content = template_file.read_text('utf-8')
                        ast = env.parse(content)
                        all_vars.update(meta.find_undeclared_variables(ast))
                    except Exception as e:
                        rich_echo(f"  [警告] 解析模板 '{template_file.relative_to(templates_dir)}' 失败: {e}", fg=typer.colors.YELLOW)
            required_vars = all_vars
    
    context, repo_root = load_and_process_configs(
        project_root,
        no_project_config,
        global_config_paths or [],
        config_paths or [],
        repo_root_override,
        set_vars or [],
        required_vars=required_vars
    )

    import json
    # 使用 default=str 来处理 Path 等不可序列化对象
    rich_debug(f"最终上下文准备就绪: {json.dumps(context, indent=2, default=str)}")
    
    rich_echo("--- 4. 开始渲染 ---", bold=True)
    
    if stdin_content is not None or template_path:
        # Note: template_content is already loaded from above
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
            
            # --- Post-Render Evaluation ---
            # If the entire rendered output is another dynamic variable, process it.
            if output.startswith('$'):
                # The key_path 'final_render' is arbitrary for logging purposes.
                final_output = process_value("final_render", output[1:], repo_root)
                print(final_output, end='')
            else:
                print(output, end='')

        except Exception as e:
            rich_echo(f"[错误] 渲染模板失败: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
            
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