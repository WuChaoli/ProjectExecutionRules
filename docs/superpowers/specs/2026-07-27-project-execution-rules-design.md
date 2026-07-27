# Project Execution Rules 设计

## 1. 背景

现有项目治理实践已经证明，自动加载的入口文档、按领域拆分的规则、项目级覆盖、
确定性结构检查和只读 Agent 审查可以共同降低上下文噪声，并提高规则的可发现性、
一致性和可维护性。

现有实现仍然存在以下通用化问题：

- `spec` 命名更接近设计规格，而实际内容主要是约束 Agent 行为的执行规则；
- 固定领域集合与 Python 项目绑定，难以扩展其他语言和技术栈；
- 初始化、安装、更新、修复和结构检查依赖分散脚本；
- 用户级资源和项目级资源缺少统一的交互式生命周期入口；
- Rule 的加载时机没有成为正式数据模型，难以兼容路径触发机制；
- 规则治理和项目功能审计容易混为同一职责。

本项目将这些能力整理为一个独立、版本化、可离线安装的交互式 CLI。

## 2. 产品目标

`ProjectExecutionRules` 负责保证项目拥有一套完整、一致、可触发、可加载、
可维护和可回滚的执行规则。

首版提供：

- 内置的语言无关 Core Rules；
- 完整的 Python Profile；
- Codex CLI Adapter；
- 用户级 Rules、Agent 和 Skill 的安装与更新；
- 项目 `AGENTS.md`、`.rules/` 和 Rule Override 的初始化；
- Rules 结构、触发器、预算、版本和加载入口检查；
- Rules 文档本身的只读语义审查；
- 受控的 Rules 结构修复和事务回滚；
- 默认交互式、可供脚本使用的非交互和 JSON 输出模式。

## 3. 首版适用范围

首版固定支持：

- 单用户；
- 单项目操作；
- Windows；
- 本地运行；
- Codex CLI；
- Python 实现的 CLI；
- 完整 Python Profile；
- 离线内置资源；
- Git 仓库。

首版架构允许未来增加其他语言 Profile 和 Agent Adapter，但不实现这些扩展。

## 4. 明确非目标

首版不负责：

- 审计业务代码是否符合 Rules；
- 判断架构、测试覆盖或业务功能是否正确；
- 运行 Ruff、Pyright、pytest 或项目构建命令；
- 访问真实外部服务；
- 修改业务代码；
- 执行 PR、CI、发布或部署；
- 生成和管理业务 Finding；
- 执行 Harness 项目成熟度评分；
- 支持团队同步、远程 Registry、多用户权限或云端状态；
- 支持 Claude Code、Cursor、GitHub Copilot 等其他 Agent；
- 自动修改 `.codex/config.toml`。

Rules 可以描述项目应执行哪些验证，但本 CLI 不代替项目或其他 Agent 执行这些验证。

## 5. 命名

统一使用 `Rules` 表达运行时治理内容：

| 对象 | 名称 |
|---|---|
| Repository | `ProjectExecutionRules` |
| Python distribution | `project-execution-rules` |
| Python package | `project_execution_rules` |
| CLI command | `project-rules` |
| 用户级 Rule Home | `%USERPROFILE%\.agents\rules\` |
| 项目 Rule 目录 | `.rules/` |
| Base Rule | `<domain>-rules.md` |
| 项目覆盖 | `<domain>-rules.override.md` |
| Rule Catalog | `catalog.yaml` |
| 项目 Rule Set | `.rules/ruleset.yaml` |

设计文档仍可使用 Design Spec，因为它描述产品设计，而不是运行时执行规则。

## 6. 总体架构

采用模块化单体 Python CLI。首版不开放第三方动态插件，但内部边界必须允许新增
Profile 和 Adapter。

```text
Interactive CLI / Automation CLI
                |
        Application Commands
                |
       Governance Services
  detection / catalog / diff / transaction
                |
          Adapter Layer
             Codex
                |
          Rules Profiles
        Core + Python Profile
                |
   Filesystem / Git / Codex CLI
```

### 6.1 组件职责

`cli`：

- 呈现交互式向导；
- 解析非交互参数；
- 提供稳定退出码和 JSON 输出；
- 不承载规则判断逻辑。

`application`：

- 编排 install、init、check、review、update、repair 和 rollback；
- 建立授权边界；
- 组合事务、验证与报告。

`governance`：

- 解析 Rule Catalog 和 Rule Set；
- 检查 Rule ID、触发器、预算、版本和覆盖关系；
- 生成预览和差异；
- 计算项目治理状态。

`adapters.codex`：

- 渲染最小 `AGENTS.md`；
- 安装 Codex Agent 和 Skill；
- 验证 Codex 加载入口；
- 启动只读 Rules Reviewer；
- 不修改 `.codex/config.toml`。

`profiles`：

- Core 提供语言无关规则；
- Python Profile 提供 Python 语言和生态规则；
- Profile 通过稳定接口声明 Rule、触发器、依赖和模板。

`transactions`：

- 将用户级和项目级写入分为独立事务；
- 写入前备份全部目标；
- 验证失败时恢复并复验；
- 只有成功恢复或成功完成后才能清理备份。

## 7. Rules 分层

### 7.1 Core Rules Catalog

Core Rules 与语言无关：

```text
security
testing
documentation
git
pull-request
ci-cd
debug
observability
architecture
external-services
agent
tool
harness
```

Core 表示可被所有 Profile 复用，不表示所有 Rule 无条件加载。项目只选择真实适用的
Rule。

### 7.2 Python Profile

首版只交付完整 `python-rules.md`，负责：

- Python 版本和项目元数据事实来源；
- 包管理器和锁文件识别；
- 模块、导入、副作用和公共接口约束；
- Python 格式、Lint、类型检查和测试工具的发现规则；
- 与 Core Testing、Architecture 和 External Services Rules 的职责边界。

`pytest` 等具体工具属于 Python Profile 对 Core Rule 的实现选择，不能复制 Core
Testing Rules 的通用原则。

### 7.3 Override

`<domain>-rules.override.md` 只保存当前项目的真实差异：

- 具体 Python 版本；
- 实际包管理器；
- 实际目录；
- 实际质量门禁；
- 当前项目特有边界。

Override：

- 必须是 Git 跟踪的普通文件；
- 不得是软链接、junction 或其他 reparse point；
- 不得复制 Base Rule；
- 没有差异时不得创建；
- 不得降低不可覆盖的安全内核；
- 默认继承 Base Rule 的触发器；
- 可以缩小路径触发范围，首版不得扩大范围。

## 8. Rule 文档模型

### 8.1 Rule ID

每条稳定规则使用不可复用的 ID：

```text
SEC-001
TST-001
DOC-001
GIT-001
PR-001
CICD-001
DBG-001
OBS-001
ARC-001
EXT-001
AGT-001
TOL-001
HAR-001
PY-001
PY-OVR-001
```

删除的 ID 标记 deprecated，不得赋予新语义。CLI 机械检查 ID 唯一性和合法前缀。

### 8.2 正文结构

Base Rule 推荐包含：

```text
标题
事实来源
执行规则
验证要求
职责边界
```

章节名称不是结构合法性的唯一条件。规则质量以是否明确、稳定、可执行和可验证为准。

### 8.3 内容预算

| 内容 | 软上限 | 硬上限 |
|---|---:|---:|
| 项目 `AGENTS.md` | 6 KiB | 8 KiB |
| 单个 Base Rule | 4 KiB | 8 KiB |
| 单个 Override | 2 KiB | 4 KiB |
| 普通任务首次加载 | 16 KiB | 24 KiB |

普通任务首次最多选择两个直接相关领域，之后按执行阶段增量加载。

## 9. Rule 触发模型

Rule Trigger 是一等数据：

```text
always
paths
task
explicit
```

- `always`：最小安全内核；
- `paths`：读取匹配路径时生效；
- `task`：进入 Git、测试、文档等任务阶段时生效；
- `explicit`：仅显式进行 Agent、Tool 或 Harness 治理时生效。

### 9.1 Claude 兼容路径触发

路径触发 Rule 使用 Claude Code 兼容的 YAML frontmatter：

```markdown
---
paths:
  - "**/*.py"
  - "pyproject.toml"
  - "uv.lock"
---

# Python Rules
```

没有路径触发的 Rule 不写空 `paths`。

Rule Catalog 保存完整触发类型；Markdown frontmatter 保存原生路径触发。CLI 必须验证
两者一致。

### 9.2 Codex 映射

Codex Adapter 映射为：

```text
always   -> AGENTS 最小安全内核
paths    -> AGENTS 领域路由
task     -> AGENTS 阶段路由
explicit -> Agent 或 Skill 显式入口
```

未来 Claude Adapter 可以映射为：

```text
always   -> 无 paths 的 .claude/rules/*.md
paths    -> 有 paths 的 .claude/rules/*.md
task     -> Claude Skill
explicit -> Claude Skill 或 Agent
```

该映射只是未来兼容性约束，不属于首版交付。

### 9.3 Trigger 验证

CLI 检查：

- `paths` 必须是项目相对 Glob；
- 禁止绝对路径和 `..` 越界；
- 禁止空 `paths`；
- Catalog 与 frontmatter 必须一致；
- Override 不得扩大 Base 的路径范围；
- `always` 总量不得超过启动预算；
- `task` 和 `explicit` Rule 不得被渲染为无条件规则；
- Python Profile 必须覆盖 `.py`、`pyproject.toml` 和已探测到的锁文件。

## 10. 用户级与项目级布局

### 10.1 CLI 内置资源

```text
project_execution_rules/resources/
├── catalog.yaml
├── rules/
│   ├── core/
│   └── profiles/python/
├── adapters/codex/
├── agents/
├── skills/
├── schemas/
└── templates/
```

资源随 Python distribution 发布，运行时不从网络下载。

### 10.2 用户级安装

```text
%USERPROFILE%\.agents\rules\
%USERPROFILE%\.codex\agents\
%USERPROFILE%\.codex\skills\
```

CLI 只修改自己管理且能够验证身份的资源。既有同名非托管文件属于冲突，不得覆盖。

### 10.3 项目初始化

```text
project/
├── AGENTS.md
└── .rules/
    ├── ruleset.yaml
    ├── python-rules.md
    ├── python-rules.override.md
    └── ...
```

Base Rule 使用只读符号链接指向用户级 canonical Rule。Override 是项目内普通文件。

Windows 初始化前必须验证符号链接能力。首版不静默降级为文件复制；不具备链接能力时
停止并提供 Developer Mode 或权限修复建议。

## 11. Rule Set

`.rules/ruleset.yaml` 是受 Git 跟踪的项目期望状态：

```yaml
schema_version: 1
rules_version: 1.0.0
adapter: codex
profile: python

domains:
  core:
    - security
    - testing
    - documentation
    - git
    - pull-request
    - ci-cd
    - debug
    - observability
    - architecture
    - agent
    - tool
    - harness
  profile:
    - python

overrides:
  - python
  - testing
  - architecture
```

Rule Set 不保存：

- PID；
- 日志；
- 绝对本机路径；
- 临时事务；
- 凭据；
- `.env` 内容；
- 审计缓存。

## 12. CLI 命令

```text
project-rules
├── install
├── init
├── status
├── check
├── review
├── doctor
├── update
├── repair
├── rollback
└── uninstall
```

无参数执行时进入交互式主菜单。所有命令同时提供：

- 明确参数的非交互模式；
- `--format json`；
- 稳定退出码；
- 修改命令的 `--dry-run`；
- 非交互写入所需的显式 `--yes`。

### 12.1 `install`

安装内置用户级 Rule、Codex Agent 和 Skill。安装前展示用户级变更，并使用独立事务。

### 12.2 `init`

交互流程：

```text
选择项目
-> 探测 Git 和 Python 项目事实
-> 推荐 Python Profile
-> 选择适用 Core Rules
-> 展示触发器和预算
-> 检查用户级资源
-> 分别预览用户级与项目级变更
-> 分别授权
-> 事务写入
-> 自动 check
```

`init` 不自动创建空 Override，不修改 CI、Codex 配置或业务代码，也不提交 Git。

### 12.3 `status`

显示项目 Profile、Adapter、Rule Version、治理状态和漂移摘要。

### 12.4 `check`

只执行确定性检查：

- 加载链；
- Rule Set；
- 链接；
- Git 跟踪；
- ID；
- Trigger；
- 预算；
- checksum；
- 版本；
- AGENTS 路由覆盖。

不启动 Agent，不运行项目命令。

### 12.5 `review`

启动只读 Codex Rules Reviewer，只审查：

- Rule 是否完整；
- 规则是否明确、无重复和无矛盾；
- Trigger 是否符合规则语义；
- Rule 是否具有可执行和可验证的表述；
- 内容是否放在正确层级；
- Override 是否只包含项目差异。

Reviewer 不审计业务代码，不运行测试，不生成业务 Finding，不修改文件。

### 12.6 `doctor`

检查：

- Windows 和 Python 运行环境；
- Codex CLI 可发现性；
- 用户级目录权限；
- 符号链接能力；
- Git 仓库；
- Rule、Agent 和 Skill 入口；
- 未完成事务；
- CLI、Schema 和 Rules 版本兼容性。

`doctor` 不运行项目质量命令。

### 12.7 `update`

比较 CLI 内置资源、用户级安装和项目 Rule Set，展示：

- 新增、修改、废弃的 Rule；
- Rule ID 变化；
- Trigger 变化；
- Override 潜在冲突；
- 受影响项目文件；
- Schema 兼容性。

只有用户确认后才分别更新用户级和项目级资源。

### 12.8 `repair`

只修复：

- 缺失或错误链接；
- AGENTS 路由；
- Rule Set 结构；
- Trigger/frontmatter 不一致；
- 托管 Agent/Skill 入口；
- CLI 管理的文件漂移。

语义不明确、非托管文件冲突、安全内核降级或需要修改业务代码时必须停止。

### 12.9 `rollback`

只恢复 CLI 创建的事务。目标身份、事务状态或恢复边界不明确时拒绝执行。

### 12.10 `uninstall`

分别处理项目资源和用户级资源。只删除能够用 manifest 和 checksum 确认为 CLI
管理的内容；Override 和用户创建内容默认保留。

## 13. 状态模型

```text
unmanaged
    |
   init
    v
planned
    |
 confirm
    v
managed
├── healthy
├── drifted
├── update_available
└── incompatible
```

状态必须从真实文件重新计算：

- `unmanaged`：不存在有效 Rule Set；
- `planned`：计划已生成但尚未写入；
- `healthy`：链接、版本、路由、Trigger 和预算一致；
- `drifted`：托管文件缺失、损坏或被修改；
- `update_available`：内置版本高于项目声明版本；
- `incompatible`：Schema、CLI、Adapter 或 Rule Version 不兼容。

## 14. 事务与本机状态

所有治理资源写入执行：

```text
inspect
-> plan
-> preview
-> authorize
-> backup
-> apply
-> verify
-> cleanup
```

失败时执行：

```text
failure
-> restore
-> verify restoration
-> cleanup on verified restoration
```

恢复失败必须保留备份并输出明确错误，不继续修改。

本机状态：

```text
%LOCALAPPDATA%\ProjectExecutionRules\
├── transactions/
├── backups/
├── review-cache/
└── registry.json
```

用户级资源和项目级资源必须使用独立事务、独立授权和独立回滚。

## 15. 错误处理

错误分为：

- `usage_error`：参数或交互输入无效；
- `environment_error`：Codex、Git、权限或链接环境不可用；
- `structure_error`：Rule Set、链接、Trigger 或路由错误；
- `conflict_error`：托管目标与既有非托管内容冲突；
- `compatibility_error`：版本或 Schema 不兼容；
- `transaction_error`：备份、写入、验证或恢复失败；
- `review_error`：Codex Reviewer 无法启动或返回无效报告。

交互模式必须解释下一步；JSON 模式返回稳定 code、message、evidence 和 remediation。
任何错误都不得通过跳过验证、覆盖非托管文件或扩大授权来自动恢复。

## 16. 安全边界

- 不读取 `.env`、凭据、密钥、PID、运行日志或本机服务状态；
- 不从 Rule Markdown 提取并执行命令；
- 不运行项目测试、构建或外部服务；
- 不修改业务代码；
- 不自动修改 `.codex/config.toml`；
- 不覆盖非托管同名资源；
- 不通过项目 Base 链接写入用户级 canonical Rule；
- 用户级和项目级写入分别授权；
- 删除前必须验证精确目标和托管身份；
- 日志和报告不得包含文件正文中的秘密；
- `review` Agent 必须只读。

## 17. 测试策略

首版测试包括：

### 17.1 单元测试

- Catalog 和 Rule Set 解析；
- Rule ID；
- Trigger 和 Glob；
- 预算；
- 状态计算；
- 差异和升级兼容性；
- 事务状态机；
- JSON Schema 和退出码。

### 17.2 Fixture 测试

至少覆盖：

- 未管理 Python 项目；
- 健康项目；
- 缺失 Base 链接；
- Override 未跟踪；
- Trigger 漂移；
- Rule ID 重复；
- 超预算；
- 非托管文件冲突；
- 旧版本可升级；
- 不兼容 Schema；
- 符号链接不可用；
- 中途写入失败与成功恢复；
- 恢复失败并保留证据。

### 17.3 Windows 集成测试

- 用户级资源安装；
- 项目初始化；
- 符号链接创建和解析；
- Git 跟踪与 ignore；
- update dry-run；
- repair；
- rollback；
- uninstall 保留 Override；
- Codex Reviewer 只读调用。

测试不得依赖真实外部服务。

## 18. 首版验收标准

首版完成必须满足：

1. `uv tool install` 可以安装 CLI；
2. 无参数运行进入交互式向导；
3. 干净 Python Git 项目可以离线初始化；
4. 用户级资源和项目级资源分别预览、授权和事务写入；
5. 初始化结果包含最小 AGENTS、Rule Set、Base 链接和必要 Override；
6. 没有空 Override；
7. `check` 能发现链接、Trigger、ID、预算、版本和路由问题；
8. `review` 只审查 Rules，不读取或判断业务功能；
9. `repair` 不修改业务代码或非托管文件；
10. update 可以 dry-run 并报告 Override 影响；
11. 写入失败能够恢复并复验；
12. JSON 输出和退出码稳定；
13. Windows 符号链接不可用时明确停止；
14. 不读取凭据，不执行 Rule Markdown 中的命令；
15. 所有离线测试通过。

## 19. 后续扩展边界

未来可以增加：

- TypeScript、Java、Android、Rust 和 .NET Profile；
- Claude Code Adapter；
- Rules Registry 和签名包；
- 团队级版本锁定；
- 项目功能审计扩展；
- Finding 生命周期扩展；
- CI Rules Gate。

这些能力必须作为独立设计和版本发布，不能在首版中留下空实现或占位 Profile。
