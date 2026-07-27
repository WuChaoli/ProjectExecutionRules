# Project Execution Rules

Project Execution Rules 是面向本地 Codex CLI 的交互式 Rules 生命周期管理工具。
它负责安装、初始化、更新、检查、审查、修复和卸载 Rules 基础设施，不审计业务
代码，不运行项目测试、构建或外部服务。

## 首版范围

- 单用户、单项目、本地 Windows。
- Codex CLI Adapter。
- CLI 使用 Python 实现。
- Core Rules 与完整 Python Profile。
- 所有 Rule、Agent、Skill 和 Schema 随包内置，可离线使用。
- 默认交互式，同时支持 JSON 和非交互模式。

## 安装

要求：

- Python 3.11 或更高版本；
- `uv`；
- Git；
- Codex CLI；
- Windows Developer Mode 或可创建文件符号链接的权限。

从本地 checkout 安装：

```powershell
uv tool install .
project-rules --help
```

开发环境：

```powershell
uv sync --locked
uv run project-rules --help
```

## 快速开始

不带参数进入交互菜单：

```powershell
project-rules
```

先检查环境：

```powershell
project-rules doctor --root .
```

安装用户级资源：

```powershell
project-rules install --dry-run
project-rules install
```

初始化 Python 项目：

```powershell
project-rules init --root . --dry-run
project-rules init --root .
```

初始化会创建或更新：

```text
AGENTS.md
.gitignore
.rules/ruleset.yaml
.rules/<domain>-rules.md
.rules/<domain>-rules.override.md
```

Base Rule 是指向 `%USERPROFILE%\.agents\rules\` 的只读符号链接。Override 只在
探测到真实项目差异时创建，并作为普通文件加入 Git 暂存区。CLI 不自动提交。

## 检查与只读审查

确定性结构检查：

```powershell
project-rules check --root .
project-rules check --root . --format json
```

检查内容包括 Rule Set、链接、Rule ID、Trigger、AGENTS 路由、Override 跟踪、
内容预算和版本兼容性。

只读语义审查：

```powershell
project-rules review --root .
```

Reviewer 使用临时、只读 Codex 会话，只允许审查 AGENTS、Rules、Catalog 和相关
Agent/Skill 定义；它不能审计业务代码、运行项目命令或修改文件。

## 生命周期

```powershell
project-rules status --root .
project-rules update --dry-run
project-rules repair --root . --dry-run
project-rules rollback <transaction-id>
project-rules uninstall --root . --dry-run
```

所有修改遵循：

```text
inspect -> plan -> preview -> authorize -> backup -> apply -> verify
```

验证失败时自动恢复。恢复失败会保留事务证据并停止后续写入。

本机事务状态位于：

```text
%LOCALAPPDATA%\ProjectExecutionRules\
```

该目录不应提交 Git。

## Windows 符号链接

首版不在符号链接失败时复制 Base Rule。`doctor` 会执行临时链接探测；不可用时
报告 `SYMLINK_UNAVAILABLE` 并停止初始化。启用 Windows Developer Mode 或使用
具备创建符号链接权限的终端后重新运行。

## JSON 与退出码

```powershell
project-rules status --format json
project-rules install --dry-run --format json
```

- `0`：命令成功；
- `1`：使用、环境、冲突、事务或 Reviewer 错误；
- `2`：`check` 或 `doctor` 完成但发现问题。

JSON 错误固定包含 `code`、`message`、`evidence` 和 `remediation`。

## 安全边界

- 不读取 `.env`、凭据、密钥、PID 或项目日志。
- 不执行 Rule Markdown 中的命令。
- 不修改 `.codex/config.toml`。
- 不覆盖非托管同名文件。
- 不修改或删除业务代码。
- 不运行 Ruff、Pyright、pytest、构建、部署或真实外部服务。
- `uninstall` 默认保留所有 `*.override.md`。

## 开发验证

```powershell
uv sync --locked
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyright
uv run pytest -q
uv build
```

设计和实施依据：

- [首版设计](docs/superpowers/specs/2026-07-27-project-execution-rules-design.md)
- [实施计划](docs/superpowers/plans/2026-07-27-project-execution-rules-implementation.md)
