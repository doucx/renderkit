from typing import Any, Dict
import typer
from .console import rich_echo
import typer

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