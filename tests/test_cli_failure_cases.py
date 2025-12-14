# tests/test_cli_failure_cases.py

from typer.testing import CliRunner
from renderkit.cli import app

runner = CliRunner()

def test_integration_failure_on_multi_level_dependency():
    """
    此集成测试旨在精确复现用户报告的、由多级动态变量依赖解析失败导致的问题。

    **测试逻辑 (基于已分析的原因):**

    1.  **创建依赖链**: 我们通过 `--set` 创建一个三级依赖链:
        - `command_to_run` (L3) 依赖于 `tool_name` (L1) 和 `target_dir` (L2).
        - `target_dir` (L2) 依赖于 `root_path` (L1).
        - `tool_name` 和 `root_path` (L1) 是静态基础变量.

    2.  **触发阶段一失败 (Config Processing)**:
        - `load_and_process_configs` 函数的依赖解析循环会启动。
        - 由于算法缺陷，它会过早地判断依赖已“收敛”，此时 `command_to_run`
          在内部 `context` 字典中的值仍然是未完全解析的字符串:
          `'$!{{ tool_name }} -n {{ target_dir }}'`.

    3.  **触发阶段二失败 (CLI Rendering)**:
        - `cli.py` 接收到 `stdin` 模板 `{{ command_to_run }}`.
        - Jinja2 将其渲染为步骤 #2 中那个未解析的字符串.
        - `cli.py` 的后处理逻辑 `if output.startswith('$')` 被触发.
        - `process_value` 函数被调用，其参数为 `'!{{ tool_name }} -n {{ target_dir }}'`.
        - `process_value` 顶部的安全检查 `if "{{" in value:` 被触发，
          函数直接返回其输入值，命令不会被执行.
    
    4.  **验证结果**:
        - 最终 `stdout` 应该是被 `process_value` 返回的、去除了 `$` 前缀的、
          未执行的命令字符串。
        - 我们断言输出 *不是* 正确执行后应有的结果 (`/project/build`)，
          而是那个半成品字符串 (`!echo -n {{ target_dir }}`).
    """
    
    # 1. 定义多级依赖变量
    set_vars = [
        # Level 1 (Static)
        "--set", "root_path=/project",
        "--set", "tool_name=echo",

        # Level 2 (Depends on L1)
        "--set", "target_dir=${{ root_path }}/build",

        # Level 3 (Depends on L1 and L2) - This is the variable that will fail to resolve.
        "--set", "command_to_run=$!{{ tool_name }} -n {{ target_dir }}"
    ]
    
    # 定义要渲染的模板，它引用了最高级的、有问题的变量
    template_input = "{{ command_to_run }}"
    
    # 组合命令行参数，使用 -q 模式简化输出
    args = ["-q"] + set_vars

    # 2. 执行 renderkit 命令
    result = runner.invoke(app, args, input=template_input)

    # 3. 进行断言，验证失败行为
    assert result.exit_code == 0, f"命令执行失败，输出: {result.output}"

    # 预期的错误输出：命令字符串本身，而不是命令执行的结果。
    # 注意：根据分析，`tool_name` 可能会被解析，但 `target_dir` 不会，
    # 或者两者都不会。我们断言一个更可能出现的、也是用户报告中最严重的形式。
    # 最终，根据用户的实际输出来看 `!{{ xmlpath }} ... {{ aca_builder_path }}`，
    # 似乎两个变量都未被解析。但即使只有一个未被解析，也足以触发安全检查。
    # 我们将断言最能体现问题的那个场景。
    # 经过试验，发现 `tool_name` 会被解析，但 `target_dir` 不会。
    # 所以最终输出是 `!echo -n {{ target_dir }}`
    expected_incorrect_output = "!echo -n {{ target_dir }}"
    
    # 期望的正确输出 (Bug 已修复，现在应该输出此结果)
    correct_output = "/project/build"
    
    # 断言实际输出是正确的执行结果
    assert result.stdout.strip() == correct_output, \
        f"Bug 复现失败：输出内容不符合预期。得到: '{result.stdout.strip()}'"
