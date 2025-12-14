from pathlib import Path
import yaml
from renderkit.config import load_and_process_configs

def test_config_loading_basic(project_dir: Path):
    context, _ = load_and_process_configs(project_dir, False, [], [], None, [])
    assert context["project_name"] == "TestProject"
    assert "KOS" in context
    assert context["KOS"]["version"] == "1.0.0"

def test_config_loading_with_set_override(project_dir: Path):
    context, _ = load_and_process_configs(project_dir, False, [], [], None, ["KOS.version=2.0.0"])
    assert context["KOS"]["version"] == "2.0.0"

def test_config_loading_with_global_override(project_dir: Path):
    override_g_path = project_dir / "override_g.yaml"
    override_g_path.write_text(yaml.dump({"project_name": "Overridden"}))
    
    context, _ = load_and_process_configs(project_dir, False, [override_g_path], [], None, [])
    assert context["project_name"] == "Overridden"

def test_config_loading_no_project_config(project_dir: Path):
    # This should result in an almost empty context
    context, _ = load_and_process_configs(project_dir, True, [], [], None, [])
    assert "project_name" not in context
    assert "KOS" not in context
    assert "repo_root" in context # repo_root is auto-detected

def test_config_dynamic_resolution(project_dir: Path):
    # Test recursive resolution: full -> part -> base
    # And referencing a --set variable
    
    set_vars = [
        "base=World",
        "part=$Hello {{ base }}",
        "full=$Prefix: {{ part }}",
        "literal=$Just String"
    ]
    
    context, _ = load_and_process_configs(project_dir, True, [], [], None, set_vars)
    
    assert context["base"] == "World"
    assert context["part"] == "Hello World"
    assert context["full"] == "Prefix: Hello World"
    assert context["literal"] == "Just String"

def test_config_dynamic_combined_syntax(project_dir: Path):
    """
    测试 '$' 与 '!' 和 '@' 组合语法的正确性。
    验证变量可以先被渲染，然后其结果被作为命令或文件路径进行二次处理。
    """
    # 准备用于动态文件路径测试的文件
    dynamic_file = project_dir / "dynamic.txt"
    dynamic_file.write_text("Dynamic file content")

    set_vars = [
        "command_name=echo",
        'dynamic_command=$!{{ command_name }} "Dynamic Command Output"',
        "filename=dynamic.txt",
        "dynamic_file_content=$@{{ filename }}",
    ]

    # 使用 project_dir 作为 repo_root 以便 '@' 可以正确解析
    context, _ = load_and_process_configs(project_dir, True, [], [], project_dir, set_vars)

    # 验证动态命令
    assert "dynamic_command" in context
    assert context["dynamic_command"] == "Dynamic Command Output"

    # 验证动态文件引用
    assert "dynamic_file_content" in context
    assert context["dynamic_file_content"] == "Dynamic file content"


def test_config_direct_command_execution(project_dir: Path):
    """
    测试不带 '$' 前缀的命令 (`!`) 和文件 (`@`) 引用是否能被正确执行。
    这是为了防止 `PlanExecutor` 逻辑回归，它必须处理所有特殊值，而不仅仅是
    那些通过 '$' 渲染而来的值。
    """
    set_vars = [
        'direct_command=!echo "Direct Execution Works"',
    ]

    # 使用 project_dir 作为 repo_root 以便 '@' 可以正确解析
    context, _ = load_and_process_configs(project_dir, True, [], [], project_dir, set_vars)

    # 验证直接命令
    assert "direct_command" in context
    assert context["direct_command"] == "Direct Execution Works"