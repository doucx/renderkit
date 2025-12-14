import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
from renderkit.cli import app

runner = CliRunner()

def test_final_output_is_dynamically_evaluated(tmp_path: Path):
    """
    测试当 stdin/template 的渲染结果本身是一个动态变量时，系统是否会对其进行二次求值。
    这模拟了 `echo "{{ ACADATA.some_command }}" | rk` 的场景。
    """
    # 1. 创建项目结构和配置
    (tmp_path / "configs").mkdir()
    
    # config.yaml 定义基础变量
    (tmp_path / "config.yaml").write_text("""
tool_path: 'echo'
target_dir: 'final_target'
    """)
    
    # data.yaml 定义一个动态命令，它引用了 config.yaml 中的变量
    (tmp_path / "configs" / "data.yaml").write_text("""
command: '$!{{ tool_path }} {{ target_dir }}'
    """)

    # 2. Mock subprocess.run
    with patch("subprocess.run") as mock_run:
        # 模拟 echo 命令的行为，它会返回它收到的参数
        def side_effect(cmd, **kwargs):
            if cmd.startswith("echo"):
                return MagicMock(stdout=cmd[5:].strip(), returncode=0)
            # 对于其他任何命令，返回一个标准响应
            return MagicMock(stdout="default mock output", returncode=0)
            
        mock_run.side_effect = side_effect
        
        # 3. 执行 renderkit
        # 我们通过 stdin 传入一个引用动态命令的模板
        result = runner.invoke(
            app,
            ["-d", str(tmp_path), "-q"],
            input="{{ data.command }}"
        )
        
        # 4. 验证
        assert result.exit_code == 0, f"CLI exited with error: {result.output}"
        
        # 预期输出应该是 'echo' 命令执行后的结果，而不是命令本身
        # 错误的行为会输出：$!echo final_target
        # 正确的行为会输出：final_target
        assert result.stdout.strip() == "final_target"
        
        # 验证 'echo' 命令是否被正确地调用了
        mock_run.assert_called_with(
            "echo final_target",
            shell=True,
            capture_output=True,
            text=True,
            check=True,
            encoding='utf-8',
            cwd=tmp_path.resolve()
        )