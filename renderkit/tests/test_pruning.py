import pytest
from typer.testing import CliRunner
from pathlib import Path
from renderkit.cli import app

runner = CliRunner()

def test_pruning_prevents_unnecessary_sibling_execution():
    """
    测试剪枝逻辑的有效性。
    场景：
    config:
      OPTIM:
        light: "Safe"
        heavy: "$!touch heavy_was_here"
    
    模板: "{{ OPTIM.light }}"
    
    期望：
    1. 渲染成功，输出 "Safe"。
    2. 'heavy' 变量不应被计算，因此 "heavy_was_here" 文件不应存在。
    
    如果剪枝逻辑退化（例如保留了顶层 'OPTIM' 键），依赖图构建器会错误地认为需要计算整个 'OPTIM' 命名空间，
    从而导致 'heavy' 被执行。
    """
    with runner.isolated_filesystem() as fs:
        fs_path = Path(fs)
        (fs_path / "configs").mkdir()
        
        # 定义一个包含副作用命令的变量
        side_effect_file = fs_path / "heavy_was_here"
        
        (fs_path / "config.yaml").write_text(f"""
OPTIM:
  light: "Safe"
  heavy: "$!touch {side_effect_file.name}"
        """)
        
        # 1. 执行渲染，只请求轻量级变量
        result = runner.invoke(app, ["-d", ".", "-q"], input="{{ OPTIM.light }}")
        
        assert result.exit_code == 0
        assert "Safe" in result.stdout
        
        # 2. 关键断言：验证副作用文件不存在
        assert not side_effect_file.exists(), \
            "剪枝失败：'OPTIM.heavy' 被执行了，说明整个 'OPTIM' 命名空间被错误加载。"

def test_pruning_allows_whole_object_access():
    """
    反向测试：确保当我们确实请求整个对象时，所有子节点都会被执行。
    这是为了确保我们没有过度剪枝。
    """
    with runner.isolated_filesystem() as fs:
        fs_path = Path(fs)
        (fs_path / "configs").mkdir()
        
        side_effect_file = fs_path / "heavy_executed"
        
        (fs_path / "config.yaml").write_text(f"""
OPTIM:
  light: "Safe"
  heavy: "$!touch {side_effect_file.name}"
        """)
        
        # 请求整个 OPTIM 对象
        result = runner.invoke(app, ["-d", ".", "-q"], input="{{ OPTIM }}")
        
        assert result.exit_code == 0
        
        # 此时应该执行了 heavy
        assert side_effect_file.exists(), \
            "过度剪枝：请求整个对象 '{{ OPTIM }}' 时，子节点未被执行。"