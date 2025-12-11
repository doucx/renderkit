import pytest
import yaml
from pathlib import Path

@pytest.fixture(scope="function")
def project_dir(tmp_path: Path) -> Path:
    """Creates a temporary project structure for testing."""
    # Create directories
    (tmp_path / "configs").mkdir()
    (tmp_path / "templates" / "KOS").mkdir(parents=True)
    (tmp_path / "files").mkdir()

    # Create config.yaml
    config_yaml_content = {
        "project_name": "TestProject",
        "repo_root": str(tmp_path)
    }
    (tmp_path / "config.yaml").write_text(yaml.dump(config_yaml_content), "utf-8")

    # Create configs/KOS-main.yaml
    kos_main_yaml_content = [
        {"version": "1.0.0"},
        {"author": "RenderKit"},
    ]
    (tmp_path / "configs" / "KOS-main.yaml").write_text(yaml.dump(kos_main_yaml_content), "utf-8")

    # Create templates/template.md
    (tmp_path / "templates" / "template.md").write_text(
        "Project: {{ project_name }}\n"
        "Version: {{ KOS.version }}"
    )
    
    # Create templates/KOS/scoped.md
    (tmp_path / "templates" / "KOS" / "scoped.md").write_text(
        "Scoped Version: {{ version }}\n"
        "Scoped Author: {{ author }}"
    )

    # Create file for @ reference
    (tmp_path / "files" / "data.txt").write_text("Hello from file")

    return tmp_path