import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from renderkit.config import load_and_process_configs
import subprocess

def test_recursive_dependency_execution_order(tmp_path: Path):
    """
    测试多层递归依赖时的执行顺序。
    场景：
    1. root: 基础变量
    2. intermediate: 依赖 root 的动态变量
    3. command: 依赖 intermediate 的命令变量
    
    如果顺序错误，command 会在 intermediate 被完全解析前执行，
    导致命令参数中包含 '{{' 字符。
    """
    
    # 模拟项目结构
    (tmp_path / "configs").mkdir()
    (tmp_path / "config.yaml").write_text("project_name: Test\nrepo_root: '.'")
    
    # 设置变量
    # 注意：我们故意不通过文件加载，而是通过 set_vars 注入，方便控制和测试
    # 在真实场景中，这些通常来自 yaml 文件
    
    set_vars = [
        "root=/base/path",
        # intermediate 依赖 root
        "intermediate=${{ root }}/subdir", 
        # command 依赖 intermediate
        # 如果解析过早，它会尝试执行 "echo ${{ root }}/subdir"
        "command=$!echo {{ intermediate }}"
    ]
    
    # Mock subprocess.run 来捕获错误的调用
    # 我们希望它最终被调用一次，参数是 "echo /base/path/subdir"
    # 如果参数包含 "{{", 则测试失败
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "mocked_output"
        mock_run.return_value.returncode = 0
        
        def side_effect(cmd, **kwargs):
            if "{{" in cmd or "}}" in cmd:
                raise ValueError(f"Command contains unrendered template tags: {cmd}")
            return mock_run.return_value
            
        mock_run.side_effect = side_effect
        
        try:
            # 这里的 repo_root 无所谓，因为我们不测试 @file
            load_and_process_configs(
                tmp_path, 
                no_project_config=True, 
                global_config_paths=[], 
                config_paths=[], 
                repo_root_override=None, 
                set_vars=set_vars
            )
        except ValueError as e:
            pytest.fail(str(e))
            
        # 验证是否成功调用了一次正确的命令
        # 注意：由于迭代逻辑，可能会尝试多次，但只要最终结果正确且中间没有报错即可。
        # 这里我们至少要求有一次成功的调用是完全解析后的
        
        # 检查所有调用记录
        calls = mock_run.call_args_list
        valid_call_found = False
        for call in calls:
            cmd_arg = call[0][0]
            if cmd_arg == "echo /base/path/subdir":
                valid_call_found = True
                break
        
        assert valid_call_found, f"Expected command 'echo /base/path/subdir' was not called. Calls: {calls}"

def test_mixed_recursive_dependency(tmp_path: Path):
    """
    测试更复杂的混合依赖，包括文件引用。
    """
    (tmp_path / "data.txt").write_text("file_content")
    
    set_vars = [
        "filename=data.txt",
        "file_ref=$@{{ filename }}", # 应该读取 data.txt
        "cmd_ref=$!echo {{ file_ref }}" # 应该 echo "file_content"
    ]
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "echoed_content"
        
        def side_effect(cmd, **kwargs):
            if "{{" in cmd:
                raise ValueError(f"Command contains tags: {cmd}")
            return mock_run.return_value
        mock_run.side_effect = side_effect
        
        context, _ = load_and_process_configs(
            tmp_path, True, [], [], tmp_path, set_vars
        )
        
        assert context["file_ref"] == "file_content"
        # 确认最终命令执行结果被捕获
        assert context["cmd_ref"] == "echoed_content" 