import pytest
from typer.testing import CliRunner
from pathlib import Path
from renderkit.cli import app

runner = CliRunner()

def test_lazy_execution_skips_unreferenced_commands():
    """
    测试按需执行（Lazy Execution）特性。
    """
    with runner.isolated_filesystem() as fs:
        fs_path = Path(fs)
        (fs_path / "configs").mkdir()
        
        # dangerous_cmd 使用 $!exit 1 模拟一个如果被执行就会导致崩溃的命令
        (fs_path / "config.yaml").write_text("""
dangerous_cmd: $!exit 1
safe_val: "I am safe"
        """)
        
        # 1. 仅引用 safe_val 的模板
        template_input = "{{ safe_val }}"
        
        # 执行命令
        result = runner.invoke(app, ["-d", ".", "-q"], input=template_input)
        
        # 断言
        assert result.exit_code == 0, f"非相关命令被执行导致失败: {result.output}"
        assert "I am safe" in result.stdout
        # 关键断言：确保 dangerous_cmd 没有被执行
        assert "命令执行失败" not in result.stderr

def test_lazy_execution_resolves_dependencies():
    """
    测试按需执行在存在依赖时的正确性。
    """
    with runner.isolated_filesystem() as fs:
        fs_path = Path(fs)
        # 确保依赖链: target -> dependency
        (fs_path / "config.yaml").write_text("""
dependency: $!echo hello
target: "$Result: {{ dependency }}"
unused: $!exit 1
        """)
        
        result = runner.invoke(app, ["-d", ".", "-q"], input="{{ target }}")
        
        assert result.exit_code == 0
        # 如果 output 包含 'Result: hello'，说明 dependency 已经被正确执行并注入
        assert "Result: hello" in result.stdout