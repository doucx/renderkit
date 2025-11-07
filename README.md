# RenderKit ✨

**一个强大的、由配置驱动的 Jinja2 命令行渲染工具**

`RenderKit` 是一个灵活的 Python 脚本，用于渲染 [Jinja2](https://jinja.palletsprojects.com/) 模板。它专为需要将多个配置文件、外部文件内容和动态命令输出组合成最终文本（如提示词、配置文件、文档等）的工作流而设计。

与简单的渲染脚本不同，`RenderKit` 提供了强大的分层配置系统、多种输入/输出模式和灵活的命令行接口，使其成为自动化和复杂项目管理的理想选择。

## 核心特性 🚀

*   **分层配置系统**: 通过项目默认配置、命令行指定的配置文件和动态参数 (`--set`) 进行多层覆盖，实现最大灵活性。
*   **多种模板源**:
    *   **目录模式**: 自动渲染 `templates/` 目录下的所有文件。
    *   **单文件模式**: 使用 `-t` 指定单个模板文件。
    *   **管道模式**: 直接从 `stdin` 接受模板内容，完美融入 Unix 工具链。
*   **强大的值处理**:
    *   **`@`**: 轻松地将项目内文件内容注入变量。
    *   **`file://`**: 引用系统上任何位置的绝对或相对路径文件。
    *   **`!`**: 执行 shell 命令并将其实时输出作为变量值。
*   **命名空间与作用域**:
    *   `configs/` 目录下的文件自动创建命名空间 (`KOS-*.yaml` -> `KOS.variable`)。
    *   为模板自动应用作用域，简化变量访问。
*   **高度可配置的 CLI**: 通过丰富的命令行选项精确控制渲染的每一个环节。

## 安装 🔧

1.  克隆本仓库或下载 `render.py` 脚本。
    ```bash
    git clone https://github.com/doucx/renderkit.git
    cd https://github.com/doucx/renderkit.git
    ```

2.  安装所需的 Python 依赖项。
    ```bash
    pip install -r requirements.txt
    ```

## 项目结构

`RenderKit` 期望一个特定的目录结构，以便在默认模式下工作：

```
.
├── render.py                # 主脚本
├── config.yaml              # 基础配置文件 (全局变量, repo_root)
├── configs/                 # 存放带命名空间的配置文件
│   ├── KOS-main.yaml
│   └── SYS-info.yaml
├── templates/               # 存放 Jinja2 模板文件
│   ├── global-template.md
│   └── KOS/                 # 子目录会自动应用 'KOS' 作用域
│       └── tool.md
└── outputs/                 # (自动创建) 存放渲染后的结果文件
```

## 使用指南

### 命令行选项

| 选项 | 别名 | 描述 |
| :--- | :--- | :--- |
| `--template` | `-t` | 指定单个模板文件进行渲染，结果输出到标准输出。 |
| `--directory` | `-d` | 指定项目根目录（用于加载配置和模板），默认为脚本所在目录。 |
| `--no-project-config` | | 禁用默认项目配置加载（`config.yaml` 和 `configs/`）。 |
| `--global-config` | `-g` | 指定一个全局配置文件进行覆盖或添加。可多次使用。 |
| `--config` | `-c` | 指定一个命名空间配置文件进行覆盖或添加。可多次使用。 |
| `--repo-root` | `-r` | 强制指定仓库根目录，用于解析 `@` 路径。 |
| `--set` | | 以 `KEY=VALUE` 格式动态设置变量，拥有最高优先级。可多次使用。 |
| `--scope` | `-s` | 为单文件或管道模式的模板提供一个默认作用域。 |
| `--quiet` | `-q` | 安静模式，抑制所有非错误和非结果的输出。 |

### 示例

#### 1. 基本用法：渲染整个项目
在项目目录下运行，`RenderKit` 会渲染 `templates/` 目录下的所有文件到 `outputs/`。
```bash
python render.py
```

#### 2. 单文件渲染
使用项目配置渲染一个特定的模板，并将结果重定向到文件。
```bash
python render.py -t templates/KOS/tool.md > final_tool.md
```

#### 3. 管道模式与动态变量
将 `echo` 的输出作为模板，并使用 `--set` 动态传入变量。
```bash
echo "User: {{ user }}, Time: {{ time }}" | python render.py --set user=$USER --set 'time=!date'
```

#### 4. 高级用法：完全独立的渲染
不受任何项目配置影响，使用指定的配置文件和作用域来渲染一个模板。
```bash
python render.py --no-project-config \
                 -c API-keys.yaml \
                 -t my_api_request.json.j2 \
                 -s API \
                 > request.json
```

#### 5. CI/CD 场景：覆盖版本号
在渲染整个项目时，从外部传入版本号来覆盖配置文件中的默认值。
```bash
python render.py --set 'KOS.version=1.5.2-beta'
```

---

## 配置指南

### 配置加载优先级 (瀑布流)

`RenderKit` 按以下顺序加载配置，后加载的会覆盖先加载的同名变量（从低到高）：

1.  **基础层**: 默认项目配置 (`config.yaml` 和 `configs/`)。
2.  **文件覆盖层**: 通过 `-g` 和 `-c` 传入的配置文件。
3.  **特定参数覆盖层**: 通过 `-r` 传入的 `repo_root`。
4.  **最终覆盖层**: 通过 `--set` 传入的动态变量 (最高优先级)。

使用 `--no-project-config` 可以完全跳过第一层。

### 特殊值语法

| 语法 | 示例 | 描述 |
| :--- | :--- | :--- |
| **`@`** | `my_prompt: '@prompts/base.md'` | 包含相对于 `repo_root` 的文件内容。`@/path` 和 `@path` 均可。 |
| **`!`** | `current_git_hash: '!git rev-parse --short HEAD'` | 执行 shell 命令，并将其标准输出作为变量的值。 |
| **`file://`** | `log_file: 'file:///var/log/syslog'` | 包含位于**绝对路径**或**相对于当前工作目录**的文件内容。用于引用项目外部的文件。 |

### 文件命名约定

在 `configs/` 目录中，文件名决定了变量的命名空间。

*   `KOS-main.yaml` -> 模板中通过 `{{ KOS.variable }}` 访问。
*   `SYS-info.yaml` -> 模板中通过 `{{ SYS.variable }}` 访问。

## 开发与测试

本项目包含一个健壮的 `bash` 测试脚本，用于验证所有核心功能。

```bash
# 确保脚本有执行权限
chmod +x test.sh

# 运行测试套件
./test.sh
```

---

Happy Templating
