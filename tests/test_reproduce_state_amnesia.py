# tests/test_reproduce_state_amnesia.py

from typer.testing import CliRunner
from pathlib import Path
from renderkit.cli import app

runner = CliRunner()

def test_state_amnesia_with_file_configs():
    """
    此集成测试旨在通过模拟真实的文件加载场景，精确复现“状态失忆”的 bug。

    **测试逻辑:**

    1.  **文件结构**:
        - `config.yaml`: 定义 L1 级别的基础变量 (`tool_path`, `root_path`)。
        - `configs/bug-repro.yaml`: 定义一个命名空间 `bug_repro`，其中包含：
            - `target_dir` (L2): 依赖 `root_path` (L1)。
            - `command_to_run` (L3): 依赖 `tool_path` (L1) 和 `target_dir` (L2)。这是我们观察的目标变量。
            - `another_command` (L3): 另一个动态变量。它的存在至关重要，目的是确保在 `command_to_run` 成功解析的那个轮次（例如轮次2），上下文依然会发生变化，从而强制依赖解析循环进入下一轮（轮次3）。

    2.  **触发失败**:
        - **轮次 2 (预期)**: `command_to_run` 和 `another_command` 都被成功解析和执行。此时 `processed_context` 中的值是正确的。但是，因为上下文从字符串变成了命令输出，`has_changed` 为 `True`。
        - **轮次 3 (触发 Bug)**: 由于 `has_changed` 为 `True`，循环继续。在这一轮中，由于 `resolve_node` 函数的设计缺陷（返回新对象而非原地修改），当它重新处理 `bug_repro` 字典时，已解析的 `command_to_run` 的状态（命令输出）被其更早阶段的、未完全解析的状态所覆盖。
        - **最终状态**: 循环结束后，`processed_context` 中 `bug_repro.command_to_run` 的值是错误的、未解析的字符串。

    3.  **验证结果**:
        - `cli.py` 接收到这个错误的最终值，Jinja 将其渲染出来。
        - `cli.py` 的后处理逻辑发现输出以 `$` 开头，将其交给 `process_value`。
        - `process_value` 的安全检查检测到 `{{...}}`，拦截执行，并返回未执行的命令字符串。
        - **断言**: 我们断言最终输出**不是**正确的 `/tmp/project/build`，而是包含了未解析模板标签的字符串。
    """
    with runner.isolated_filesystem() as fs:
        fs_path = Path(fs)
        
        # 1. 创建配置文件结构
        (fs_path / "configs").mkdir()
        
        # config.yaml (L1 变量)
        (fs_path / "config.yaml").write_text("""
tool_path: echo
root_path: /tmp/project
        """)
        
        # configs/bug_repro.yaml (L2 和 L3 变量)
        # 注意：使用下划线而不是连字符，确保命名空间被解析为 'bug_repro' 而不是 'bug'
        (fs_path / "configs" / "bug_repro.yaml").write_text("""
- target_dir: ${{ root_path }}/build
- command_to_run: $!{{ tool_path }} -n {{ target_dir }}
- another_command: $!{{ tool_path }} -n /another/path
        """)
        
        # 2. 定义输入模板并执行命令
        template_input = "{{ bug_repro.command_to_run }}"
        # 使用 -d . 来指定项目根目录在当前隔离的文件系统中
        result = runner.invoke(app, ["-d", ".", "-q"], input=template_input)
        
        # 3. 进行断言
        # Bug 已修复，现在应该成功执行并输出正确结果
        assert result.exit_code == 0, f"命令执行失败: {result.output}"
        
        correct_output = "/tmp/project/build"
        
        # 断言：最终输出等于正确执行的结果
        assert result.stdout.strip() == correct_output, \
            f"状态丢失 Bug 似乎仍存在或产生其他错误。得到: '{result.stdout.strip()}'"
