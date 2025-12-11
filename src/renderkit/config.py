import yaml
import typer
from pathlib import Path
from typing import List, Optional, Dict, Any

from .console import rich_echo
from .utils import deep_merge_dicts, set_nested_key
from .processor import process_value

CONFIGS_DIR_NAME = "configs"
GLOBAL_CONFIG_FILENAME = "config.yaml"

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

    if not no_project_config:
        rich_echo(f"  正在加载项目配置: {project_root}")
        global_config_file = project_root / GLOBAL_CONFIG_FILENAME
        if global_config_file.is_file():
            global_context = yaml.safe_load(global_config_file.read_text('utf-8')) or {}
        
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

    final_context = {**global_context, **namespaced_contexts}
    
    if repo_root_override:
        rich_echo(f"  正在应用 repo_root 覆盖 (-r): {repo_root_override}")
        final_context['repo_root'] = str(repo_root_override)

    if 'repo_root' not in final_context:
        rich_echo(f"  [信息] 'repo_root' 未指定，自动设置为项目根目录: {project_root}", fg=typer.colors.BLUE)
        final_context['repo_root'] = str(project_root)

    repo_root = None
    if 'repo_root' in final_context:
        repo_root = Path(final_context['repo_root']).expanduser()
        if not repo_root.is_dir():
            rich_echo(f"  [警告] 'repo_root' 指向的路径不是有效目录: {repo_root}", fg=typer.colors.YELLOW)
            repo_root = None
    
    rich_echo("--- 2. 处理变量值 (@, !) ---", bold=True)
    processed_context = {}
    for key, value in final_context.items():
        if isinstance(value, dict):
            processed_context[key] = {}
            for ns_key, ns_value in value.items():
                processed_context[key][ns_key] = process_value(f"{key}.{ns_key}", ns_value, repo_root)
        else:
             processed_context[key] = process_value(key, value, repo_root)
    
    if set_vars:
        rich_echo("--- 3. 应用 --set 变量 ---", bold=True)
        for var in set_vars:
            if '=' not in var:
                rich_echo(f"  [警告] --set 参数格式无效，已跳过: '{var}'", fg=typer.colors.YELLOW)
                continue
            key_path, value_str = var.split('=', 1)
            processed_value = process_value(key_path, value_str, repo_root)
            set_nested_key(processed_context, key_path, processed_value)
            rich_echo(f"  - {key_path} => (processed value)")

    return processed_context