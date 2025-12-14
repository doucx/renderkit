import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from renderkit.config import load_and_process_configs

def test_multi_variable_command_execution(tmp_path: Path):
    """
    测试包含多个变量引用的命令执行场景，模拟用户报告的 failures。
    
    场景:
    aca_system: '$!{{ tool }} -e {{ target }}'
    tool: '/bin/tool'
    target: '${{ root }}/build'
    root: '/project'
    
    这涉及三层依赖：
    1. root (静态)
    2. target (依赖 root)
    3. aca_system (依赖 tool 和 target)
    """
    
    # 准备环境
    (tmp_path / "configs").mkdir()
    (tmp_path / "config.yaml").write_text("root: /project")
    
    set_vars = [
        "tool=echo",
        # target 依赖 root，初始值为 ${{ root }}/build
        "target=${{ root }}/build",
        # aca_system 依赖 tool 和 target
        # 如果过早解析，target 还是 raw string，导致命令变成 "echo -e ${{ root }}/build"
        "aca_system=$!{{ tool }} arg {{ target }}"
    ]
    
    # Mock subprocess
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "tool output"
        mock_run.return_value.returncode = 0
        
        def side_effect(cmd, **kwargs):
            # 严厉的检查：绝对不允许执行包含 {{ 的命令
            if "{{" in cmd:
                raise ValueError(f"CRITICAL: Attempted to execute unparsed command: {cmd}")
            # 模拟 echo 的行为，返回参数以便验证
            if cmd.startswith("echo"):
                return MagicMock(stdout=cmd[5:], returncode=0)
            return mock_run.return_value
            
        mock_run.side_effect = side_effect
        
        # 执行
        context, _ = load_and_process_configs(
            tmp_path, 
            no_project_config=False, # 必须为 False 才能加载 config.yaml 中的 'root'
            global_config_paths=[], 
            config_paths=[], 
            repo_root_override=None, 
            set_vars=set_vars
        )
        
        # 验证结果
        # 最终 aca_system 应该是命令的输出，即 "arg /project/build"
        expected_cmd_arg = "arg /project/build"
        assert context["target"] == "/project/build"
        assert context["aca_system"].strip() == expected_cmd_arg

def test_failure_handling_in_loop(tmp_path: Path):
    """
    测试当依赖项本身就是一个包含 {{ 的字符串（非模板）时，是否会陷入死循环。
    如果 target 的值就是 '{{ not a var }}'，系统应该能够区分“未解析”和“值本身包含花括号”。
    
    注意：当前的简单的 'in' 检查无法区分。这可能是一个潜在 bug，但本测试旨在确立当前行为边界。
    如果系统设计为支持这种区分，测试应通过；否则我们记录这个限制。
    
    当前逻辑：如果 value 包含 {{，就回滚。
    这意味着：用户不能拥有值包含 {{ 的最终变量，除非该变量不通过 $ 解析。
    
    用例：
    static_var: "some {{ text }}"  <- 静态加载，不通过 resolve_node，应该没问题。
    dynamic_var: "$echo {{ static_var }}" <- 渲染后 "echo some {{ text }}"。process_value 拒收。回滚。
    
    这将导致 dynamic_var 永远无法解析，最终保留为 "$echo {{ static_var }}"。
    """
    set_vars = [
        "static_val=has {{ braces }}",
        "dynamic_ref=$!echo '{{ static_val }}'"
    ]
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "has {{ braces }}"
        
        context, _ = load_and_process_configs(
            tmp_path, True, [], [], tmp_path, set_vars
        )
        
        # 预期：系统识别出渲染结果中包含危险的 '{{' 字符，触发安全拦截。
        # process_value 会记录安全警告并返回渲染后的字符串（去除 $ 前缀，但不执行 ! 命令）。
        # 因此，值应该是 "!echo 'has {{ braces }}'"
        expected_val = "!echo 'has {{ braces }}'"
        assert context["dynamic_ref"] == expected_val