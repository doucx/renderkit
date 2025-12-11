import pytest
from typer.testing import CliRunner
from pathlib import Path
from renderkit.cli import app

runner = CliRunner()

def create_project_structure(base_path: Path):
    """Helper function to create the test project structure inside the isolated filesystem."""
    (base_path / "configs").mkdir()
    (base_path / "templates" / "KOS").mkdir(parents=True)
    
    (base_path / "config.yaml").write_text("""
project_name: TestProject
repo_root: '.'
    """)
    
    (base_path / "configs" / "KOS-main.yaml").write_text("""
- version: 1.0.0
- author: RenderKit
    """)
    
    (base_path / "templates" / "template.md").write_text(
        "Project: {{ project_name }}\nVersion: {{ KOS.version }}"
    )
    
    (base_path / "templates" / "KOS" / "scoped.md").write_text(
        "Scoped Version: {{ version }}\nScoped Author: {{ author }}"
    )

def test_cli_directory_render():
    with runner.isolated_filesystem() as fs:
        fs_path = Path(fs)
        create_project_structure(fs_path)
        
        # Run the command from the root of the isolated filesystem
        result = runner.invoke(app, ["--quiet"])
        
        assert result.exit_code == 0, result.output
        
        output_file = fs_path / "outputs" / "template.md"
        assert output_file.exists()
        content = output_file.read_text()
        assert "Project: TestProject" in content
        assert "Version: 1.0.0" in content

        scoped_output_file = fs_path / "outputs" / "KOS" / "scoped.md"
        assert scoped_output_file.exists()
        content = scoped_output_file.read_text()
        assert "Scoped Version: 1.0.0" in content
        assert "Scoped Author: RenderKit" in content

def test_cli_single_template_render():
    with runner.isolated_filesystem() as fs:
        fs_path = Path(fs)
        create_project_structure(fs_path)
        
        template_path = "templates/template.md"
        result = runner.invoke(app, ["-t", template_path, "-q"])
        
        assert result.exit_code == 0, result.output
        assert "Project: TestProject" in result.stdout
        assert "Version: 1.0.0" in result.stdout

def test_cli_stdin_render():
    # This test does not require the filesystem and was failing due to the NameError
    result = runner.invoke(
        app, 
        ["--set", "user=tester", "-q"], 
        input="Hello, {{ user }}!"
    )
    assert result.exit_code == 0, result.output
    assert "Hello, tester!" in result.stdout

def test_cli_set_override():
    with runner.isolated_filesystem() as fs:
        fs_path = Path(fs)
        create_project_structure(fs_path)
        
        template_path = "templates/template.md"
        result = runner.invoke(app, [
            "-t", template_path,
            "--set", "project_name=CLIProject",
            "--set", "KOS.version=9.9.9",
            "-q"
        ])
        assert result.exit_code == 0, result.output
        assert "Project: CLIProject" in result.stdout
        assert "Version: 9.9.9" in result.stdout