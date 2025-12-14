from pathlib import Path
from unittest.mock import MagicMock, patch
from renderkit.processor import process_value

def test_process_value_normal_string():
    assert process_value("key", "a simple string", None) == "a simple string"

def test_process_value_at_syntax(tmp_path: Path):
    repo_root = tmp_path
    (repo_root / "test.txt").write_text("file content")
    result = process_value("key", "@test.txt", repo_root)
    assert result == "file content"

def test_process_value_at_syntax_no_repo_root():
    result = process_value("key", "@test.txt", None)
    assert "repo_root undefined" in result

def test_process_value_file_uri_absolute(tmp_path: Path):
    file_path = tmp_path / "absolute.txt"
    file_path.write_text("absolute content")
    uri = file_path.as_uri() # e.g., file:///path/to/absolute.txt
    assert process_value("key", uri, None) == "absolute content"

def test_process_value_command_execution(monkeypatch):
    mock_run = MagicMock()
    mock_run.return_value.stdout = "command output"
    monkeypatch.setattr("subprocess.run", mock_run)
    
    result = process_value("key", "!echo 'hello'", Path.cwd())
    assert result == "command output"
    mock_run.assert_called_once()