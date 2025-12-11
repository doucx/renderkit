import yaml
import typer
from pathlib import Path
from typing import List, Optional, Dict, Any, Set

from .console import rich_echo
from .utils import deep_merge_dicts, set_nested_key
from .processor import process_value, resolve_dynamic_values

CONFIGS_DIR_NAME = "configs"
GLOBAL_CONFIG_FILENAME = "config.yaml"

def load_and_process_configs(
    project_root: Path,
    no_project_config: bool,
    global_config_paths: List[Path],
    config_paths: List[Path],
    repo_root_override: Optional[Path],
    set_vars: List[str],
    required_vars: Optional[Set[str]] = None
) -> Dict[str, Any]:
    """
    根据优先级瀑布流加载、合并和处理所有配置。
    如果提供了 required_vars, 则只处理这些变量。
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
                    content = yaml.safe_load(config_file.read_text('utf-8'))
                    if not content:
                        continue

                    current_ns_context = namespaced_contexts.setdefault(prefix, {})
                    
                    if isinstance(content, dict):
                        # 直接合并字典格式的配置
                        namespaced_contexts[prefix] = deep_merge_dicts(content, current_ns_context)
                    elif isinstance(content, list):
                        # 处理列表格式的配置
                        temp_dict = {}
                        for item in content:
                            if isinstance(item, dict) and len(item) == 1:
                                key, value = next(iter(item.items()))
                                temp_dict[key] = value
                        namespaced_contexts[prefix] = deep_merge_dicts(temp_dict, current_ns_context)

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

    # --- 3. 应用 --set 变量 (最高优先级) ---
    # --set 变量必须在主处理循环之前应用，以确保依赖关系被正确解析
    if set_vars:
        rich_echo("\n--- 3. 应用 --set 变量 ---", bold=True)
        for var in set_vars:
            if '=' not in var:
                rich_echo(f"  [警告] --set 参数格式无效，已跳过: '{var}'", fg=typer.colors.YELLOW)
                continue
            key_path, value_str = var.split('=', 1)
            set_nested_key(final_context, key_path, value_str)
            rich_echo(f"  - {key_path} = (raw value)")

    # --- 迭代处理依赖 ---
    processed_context = final_context.copy()
    if required_vars is None:
        # 如果没有模板（例如，只使用--set），则所有变量都需要处理
        known_dependencies = set(processed_context.keys())
    else:
        known_dependencies = required_vars.copy()
        
    known_dependencies.add('repo_root') # Always needed
    max_passes = 5

    for i in range(1, max_passes + 1):
        rich_echo(f"\n--- 4. 处理轮次 {i} (已知依赖: {len(known_dependencies)} 个) ---", bold=True)
        
        # 步骤 4.1: 处理已知依赖 (@, !)
        context_for_this_pass = {}
        for key, value in processed_context.items():
            if key in known_dependencies:
                 if isinstance(value, dict):
                     context_for_this_pass[key] = {}
                     for ns_key, ns_value in value.items():
                         context_for_this_pass[key][ns_key] = process_value(f"{key}.{ns_key}", ns_value, repo_root)
                 else:
                     context_for_this_pass[key] = process_value(key, value, repo_root)
            else:
                context_for_this_pass[key] = value
        
        processed_context = context_for_this_pass

        # 步骤 4.2: 解析动态值 ($) 并发现新依赖
        rich_echo("  正在解析动态引用 ($)...")
        # 此时，整个上下文都用于解析，以确保跨变量引用有效
        processed_context, discovered_deps = resolve_dynamic_values(processed_context, repo_root)
        
        newly_discovered = discovered_deps - known_dependencies
        
        if not newly_discovered:
            rich_echo("  ...依赖关系已稳定。")
            break
        
        rich_echo(f"  ...发现 {len(newly_discovered)} 个新依赖项，准备下一轮处理。")
        known_dependencies.update(newly_discovered)
    else:
        rich_echo(f"[警告] 达到 {max_passes} 轮处理上限，可能存在循环依赖。", fg=typer.colors.YELLOW)

    return processed_context