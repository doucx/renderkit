import yaml
import typer
from pathlib import Path
from typing import List, Optional, Dict, Any, Set

from .console import rich_echo, rich_debug
from .utils import deep_merge_dicts, set_nested_key
from .graph import DependencyGraph
from .processor import PlanExecutor

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
    基于图的确定性配置加载流程。
    Phase 1: 加载所有原始 YAML 到一个大字典 (Raw Context)。
    Phase 2: 构建依赖图并生成执行计划 (Topological Sort)。
    Phase 3: 按计划顺序逐个渲染和执行 (Execution)。
    """
    rich_echo("--- 1. 加载配置 (Raw Loading) ---", bold=True)
    
    # --- 1. Load Raw Configs ---
    raw_context = {}
    namespaced_contexts = {}

    # 1.1 Project Configs
    if not no_project_config:
        global_config_file = project_root / GLOBAL_CONFIG_FILENAME
        if global_config_file.is_file():
            raw_context = yaml.safe_load(global_config_file.read_text('utf-8')) or {}
        
        configs_dir = project_root / CONFIGS_DIR_NAME
        if configs_dir.is_dir():
            for config_file in configs_dir.glob('*.yaml'):
                parts = config_file.stem.split('-', 1)
                if len(parts) > 0:
                    prefix = parts[0]
                    content = yaml.safe_load(config_file.read_text('utf-8'))
                    if not content: continue
                    
                    # Normalize list-of-dicts to dict
                    normalized_content = {}
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict): normalized_content.update(item)
                    elif isinstance(content, dict):
                        normalized_content = content
                    
                    current = namespaced_contexts.setdefault(prefix, {})
                    namespaced_contexts[prefix] = deep_merge_dicts(normalized_content, current)

    # 1.2 CLI Overrides (-g, -c)
    for g_path in global_config_paths:
        override = yaml.safe_load(g_path.read_text('utf-8')) or {}
        raw_context = deep_merge_dicts(override, raw_context)

    for c_path in config_paths:
        prefix = c_path.stem.split('-', 1)[0]
        override = yaml.safe_load(c_path.read_text('utf-8')) or {}
        # Normalize logic again for safety
        if isinstance(override, list):
            temp = {}
            for item in override: temp.update(item)
            override = temp
            
        current = namespaced_contexts.setdefault(prefix, {})
        namespaced_contexts[prefix] = deep_merge_dicts(override, current)

    # Merge Namespaces into Raw Context
    raw_context.update(namespaced_contexts)

    # 1.3 Handle Repo Root
    if repo_root_override:
        raw_context['repo_root'] = str(repo_root_override)
    if 'repo_root' not in raw_context:
        raw_context['repo_root'] = str(project_root)
    
    repo_root = Path(raw_context['repo_root']).expanduser()

    # 1.4 Apply --set variables (Inject into Raw Context)
    if set_vars:
        for var in set_vars:
            if '=' in var:
                key, val = var.split('=', 1)
                set_nested_key(raw_context, key, val)

    # --- 2. Build Graph & Plan ---
    rich_echo("--- 2. 构建依赖图 (Dependency Analysis) ---", bold=True)
    graph = DependencyGraph()
    graph.build(raw_context)
    
    try:
        # Pass required_vars to enable lazy execution / pruning
        plan = graph.get_execution_plan(required_vars)
        rich_echo(f"  生成执行计划: {len(plan)} 个步骤")
    except typer.BadParameter as e:
        rich_echo(f"[错误] {e}", fg=typer.colors.RED)
        raise typer.Exit(1)

    # --- 3. Execute Plan ---
    rich_echo("--- 3. 执行渲染 (Deterministic Execution) ---", bold=True)
    executor = PlanExecutor(repo_root)
    
    final_context = executor.execute(plan, {})

    return final_context, repo_root