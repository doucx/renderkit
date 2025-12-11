from pathlib import Path
import yaml
from renderkit.config import load_and_process_configs

def test_config_loading_basic(project_dir: Path):
    context = load_and_process_configs(project_dir, False, [], [], None, [])
    assert context["project_name"] == "TestProject"
    assert "KOS" in context
    assert context["KOS"]["version"] == "1.0.0"

def test_config_loading_with_set_override(project_dir: Path):
    context = load_and_process_configs(project_dir, False, [], [], None, ["KOS.version=2.0.0"])
    assert context["KOS"]["version"] == "2.0.0"

def test_config_loading_with_global_override(project_dir: Path):
    override_g_path = project_dir / "override_g.yaml"
    override_g_path.write_text(yaml.dump({"project_name": "Overridden"}))
    
    context = load_and_process_configs(project_dir, False, [override_g_path], [], None, [])
    assert context["project_name"] == "Overridden"

def test_config_loading_no_project_config(project_dir: Path):
    # This should result in an almost empty context
    context = load_and_process_configs(project_dir, True, [], [], None, [])
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
    
    context = load_and_process_configs(project_dir, True, [], [], None, set_vars)
    
    assert context["base"] == "World"
    assert context["part"] == "Hello World"
    assert context["full"] == "Prefix: Hello World"
    assert context["literal"] == "Just String"