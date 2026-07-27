# Claude Code Adapter 设计

## 1. 背景

`ProjectExecutionRules` 当前只交付 Codex CLI Adapter。Rule Catalog、Trigger、项目
Override、事务和确定性检查已经存在，但资源渲染、用户级安装、Reviewer 和环境诊断仍有
Codex 硬编码。

本设计增加 Claude Code 兼容入口，并借此把 Adapter 从设计概念落实为内部协议。此次扩展
不改变产品定位：本项目提供的是帮助目标项目建立初始执行规范并持续生长的**元规范脚手架**，
不是目标项目的测试、CI、发布或业务功能生成器。

本设计建立在 Claude Code 官方资源机制之上：

- `CLAUDE.md` 与 Rules：<https://code.claude.com/docs/en/memory>
- Skills：<https://code.claude.com/docs/en/skills>
- Subagents：<https://code.claude.com/docs/en/sub-agents>
- CLI 与诊断：<https://code.claude.com/docs/en/cli-reference>

## 2. 顶层产品决策

### 2.1 三层职责

元规范使用固定的三层执行模型：

```text
Rule  = 使用 WHEN / MUST / MUST NOT 定义触发、约束与路由
Skill = 承载 Rule 所引用的执行细节
Agent = 接受 Rule 指定的委派，分担主 Agent 的任务
```

Rule 是治理层中触发时机和执行路由的唯一规范来源。Skill 不独立定义业务触发条件，Agent 不独立
决定何时获得任务。Skill 和 Agent 的说明只描述能力，并引用负责触发它们的 Rule。

该“唯一规范来源”是本项目生成内容的治理契约，不是 Claude Code 的硬路由机制。Claude Code
仍由模型结合 Rule、Skill/Agent description 和当前上下文决定是否调用资源；本次不使用 hook
拦截或改写任意委派。

### 2.2 元规范边界

本项目只负责：

- 安装初始 Base Rules、Skills 和 Agents；
- 创建项目可继续扩展的目录、指南和 Override；
- 验证资源结构、引用闭包、托管身份和生命周期一致性；
- 在更新和卸载时保护项目已经生长出的内容。

本项目不负责：

- 生成目标项目的测试代码；
- 生成 CI Action、发布或部署配置；
- 修改目标项目业务代码；
- 执行目标项目测试、构建或质量命令；
- 将自然语言 `MUST` / `MUST NOT` 编译成 hooks 或 permissions；
- 以 Rules 充当不可绕过的安全沙箱。

具体实现方法由 Skill 指导，并在目标项目后续开发过程中完成。

### 2.3 低侵入所有权

系统级 Base 是 CLI 托管资源，可以 update、repair、rollback 和 uninstall。项目初始化生成的
指南、Override，以及项目后续新增的 Rules、Skills 和 Agents 都属于项目；生命周期命令
不得覆盖或删除这些内容。

## 3. 范围

### 3.1 本次交付

- 内部 Adapter Protocol 与 Adapter Registry；
- 现有 Codex 行为迁移到 `CodexAdapter`；
- 新增 `ClaudeAdapter`；
- `install`、`init`、`status`、`check`、`doctor`、`update`、`repair`、`rollback`、
  `uninstall` 的多 Adapter 支持；
- Codex 与 Claude 独立的托管 manifest 和事务生命周期；
- Canonical Catalog 中 Rule、Skill、Agent 及其引用关系；
- Claude 全局 Base 资源和项目生长结构；
- 自动结构测试和真实 Claude Code CLI 验收说明。

### 3.2 明确不交付

- Claude API、Claude Agent SDK 或 Managed Agents 集成；
- Claude Code Reviewer 调用入口；
- 自动驱动付费 Claude 会话的普通 CI 测试；
- 管理 `~/.claude/CLAUDE.md`；
- 自动生成项目级 Skill 或 Agent 初稿；
- 兼容旧的单值 `adapter: codex` Rule Set；
- Windows junction 作为 Claude Code 资源发现前提；
- 项目级 Claude Base Rule、Base Skill 或 Base Agent 的重复副本。

## 4. 架构

### 4.1 总体数据流

```text
Interactive CLI / Automation CLI
                |
        Application Commands
                |
    Catalog + Selection + Detection
                |
          Adapter Registry
          /              \
  CodexAdapter       ClaudeAdapter
          \              /
            ChangePlan
                |
         FileTransaction
                |
     Filesystem + Adapter CLI
```

Catalog 是唯一元规范真源。Adapter 只把 Catalog 和用户选择规划为平台资源，不直接写文件。
现有 `FileTransaction` 继续作为唯一写入执行器，负责授权后的备份、应用、验证和恢复。

### 4.2 Adapter Protocol

Adapter 必须提供以下能力：

- 标识自己的稳定 `AdapterId`；
- 检测对应 CLI 和系统级安装状态；
- 根据 Catalog 选择规划系统级资源；
- 根据项目选择规划必要项目结构和 Adapter 独立 Override；
- 声明本 Adapter 的预期托管资源；
- 检查系统级托管资源；
- 检查项目级结构和引用；
- 提供 doctor 诊断证据。

Adapter 不负责：

- 请求用户授权；
- 直接创建、覆盖或删除文件；
- 自行管理备份；
- 执行跨 Adapter 事务；
- 修改业务代码。

`update`、`repair`、`rollback` 和 `uninstall` 由通用生命周期服务根据 Adapter 的期望资源、
独立 manifest 和事务记录编排，不在每个 Adapter 中复制一套状态机。

### 4.3 Adapter Registry

内部注册表至少包含：

```text
codex
claude
```

CLI、doctor、status 和生命周期服务只能通过注册表解析 Adapter，不能在 handler 中散落
Codex/Claude 条件分支。注册表顺序是序列化和展示的规范顺序，交互选择顺序不得造成
Rule Set、manifest 或预览抖动。

### 4.4 不引入完整中间表示

本次不增加独立 MetaSpec IR 或编译器阶段。Checker 可以从 Catalog 派生轻量引用图，用于
验证 Rule → Skill → Agent 的引用闭包和循环，但引用图不是新的持久化真源。

## 5. Canonical Catalog

### 5.1 三类对象

Catalog 从仅描述 Rule 扩展为三类对象：

- Rule Definition：ID、来源、Trigger、路径、任务、显式命令和调用关系；
- Skill Definition：ID、Canonical 正文来源和 Adapter 可用性；
- Agent Definition：ID、Canonical 角色正文、固定 Skill 依赖和 Adapter 可用性。

Catalog 使用固定 schema；实现不得自行改名或增加未在 schema 中定义的持久化字段：

```yaml
schema_version: 2
rules_version: 1.0.0

rules:
  pull-request:
    file: core/pull-request-rules.md
    activation: task
    tasks:
      - pull-request
    skills:
      - pull-request
    agents:
      - rules-reviewer
    core: true
    required: false

skills:
  pull-request:
    file: pull-request/SKILL.md
    invocation: model
    adapters:
      - codex
      - claude

agents:
  rules-reviewer:
    file: rules-reviewer.md
    skills:
      - pull-request
    adapters:
      - codex
      - claude

profiles:
  python:
    - python
```

字段约束：

- Rule、Skill、Agent 各自在自己的映射内 ID 唯一，允许跨类型使用同一 ID；
- ID 统一使用小写 kebab-case，作为资源逻辑 ID；正文内的 `SEC-001` 等条款 ID 继续使用现有
  大写前缀规则，两者职责不同；
- `activation` 为 `always|paths|task|explicit`；仅对应类型允许非空 `paths`、`tasks` 或
  `commands`；
- Rule 的 `skills`、`agents` 和 Agent 的 `skills` 为逻辑 ID 列表，默认为空；
- Skill `invocation` 为 `model` 或 `user`；`user` 表示 Claude 的
  `disable-model-invocation: true` 语义；
- Adapter 列表非空、去重并按 Registry 顺序序列化；
- 未知字段、悬空引用和非法组合均为结构错误。

Catalog 是单一清单；Adapter 不维护另一套 Rule、Skill 或 Agent 列表。

### 5.2 Rule 正文契约

Base Rule 必须包含三个可识别章节：

```markdown
## WHEN
## MUST
## MUST NOT
```

- `WHEN` 描述何时适用；
- `MUST` 描述必须遵守的方向，以及何时调用哪个 Skill 或委派哪个 Agent；
- `MUST NOT` 描述不得偏离的边界。

Catalog 中的结构化引用服务于渲染和机械检查，正文服务于 Agent 执行。Checker 验证引用的对象
存在以及 Adapter 实现可用，但不从自然语言反向推断调用关系，也不判断两者语义是否完全等价。
语义一致性继续属于只读 Rules Reviewer 的职责，且本次不新增 Claude Reviewer。

### 5.3 Skill 与 Agent 正文

Skill Canonical 正文保存执行步骤、工具使用方法、检查清单和输出约定。Agent Canonical 正文
保存角色职责、工作边界和交付约定。Adapter 为各平台渲染必要的 frontmatter 或包装格式，
Canonical 正文不复制平台专有字段。

Claude Skill 和 Agent 的描述必须指出其负责的能力及关联 Rule，避免形成独立于 Rule 的第二套
路由真源。

### 5.4 引用图约束

Checker 必须验证：

- Rule 引用的 Skill 和 Agent 均存在；
- Agent 预加载的 Skill 均存在且 `invocation: model`；
- `invocation: user` 的显式 Skill 不得出现在 Agent 预加载列表；
- 所选 Adapter 支持所有被引用对象；
- 不存在对象引用自身；
- 不存在导致无限委派的 Agent 引用环；
- 项目所选 Rule 的系统级依赖已安装；
- 缺失引用是结构错误，不允许静默跳过。

## 6. Trigger 到 Claude Code 的映射

Trigger 不再映射为不同资源种类；所有执行规范都由 Rule 承载。

### 6.1 `always`

生成无 `paths` frontmatter 的全局 Claude Rule，在会话启动时加载。只允许真正普适且满足启动
预算的元规范使用 `always`。

### 6.2 `paths`

生成带 Claude Code 原生 `paths` frontmatter 的全局 Rule。`paths` 必须与 Catalog 一致，
仍遵守项目相对 Glob、禁止绝对路径和禁止 `..` 越界等现有约束。

`paths` 是上下文触发机制，不是访问控制或安全边界。

### 6.3 `task`

Claude Code 没有原生 task-scoped Rule。`task` Rule 因此渲染为始终可见的精简
`WHEN / MUST / MUST NOT` 骨架：

- `WHEN` 只保存任务识别条件；
- `MUST` 指向承载详细步骤的 Skill，必要时指向 Agent；
- `MUST NOT` 保存关键边界；
- 详细执行步骤不得复制进 Rule。

这种设计保持“触发时机由 Rule 定义”，同时控制启动上下文预算。

### 6.4 `explicit`

`explicit` 同样渲染为精简常驻 Rule，但 `WHEN` 必须要求用户明确提出对应治理任务或调用入口。
对应 Claude Skill 使用仅手动调用语义；Claude 不得依据普通任务自行进入显式治理流程。

### 6.5 Skill 和 Agent 的调用关系

- task Skill 可以由模型在适用 Rule 的 `MUST` 指示下调用；
- user-invocation Skill 设置 `disable-model-invocation: true`，只能由用户显式调用，且不得被
  Agent frontmatter 预加载；
- Agent 只在适用 Rule 指示委派时使用；
- Agent 固定预加载的 Skill 必须允许模型调用；
- Skill/Agent description 只描述能力和关联 Rule，不重新定义业务触发条件。

## 7. Claude Subagent 上下文契约

Claude Code 命名 custom subagent 使用独立上下文。根据官方机制：

- 它会获得主会话已经加载的 `CLAUDE.md` 和项目 Rules；
- 它不会获得主会话对话历史；
- 它不会继承主会话已经调用的 Skills；
- Agent frontmatter `skills` 中列出的 Skills 会在启动时注入完整内容；
- 尚未在主会话触发的 `paths` Rule 不保证在 subagent 中重新匹配；
- 内置 Explore 和 Plan Agent 不继承 `CLAUDE.md` 与 Rules。

Claude Adapter 因此生成以下最小可靠内容契约：

1. Agent 固定需要且允许模型调用的 Skill 显式列入 Agent 的预加载 Skills；
2. 用户显式 Skill 不进入 Agent 预加载列表；
3. 不假设主 Agent 已调用的 Skill 会被子 Agent继承；
4. 不假设所有 `paths` Rule 会在子 Agent 启动时重新计算；
5. 委派型 Rule 的 `MUST` 必须包含以下 Rule Brief 提示结构，指导主 Agent 在委派消息中传递
   本次动态约束；
6. Explore/Plan 等不继承 Rules 的 Agent，在相关 Rule 中被要求重述关键边界；
7. 真正不可违反的限制只能依赖 tools、permissions 或 hooks，本项目首版不自动生成后两者。

Rule Brief 的稳定提示结构为：

```text
Rule IDs
WHEN matched because
Task goal
Allowed scope
MUST
MUST NOT
Required Skills
Required checks
Expected output
```

该结构由相关 Rule 正文作为委派提示提供，不新增用户手写配置。纯资源 Adapter 无法拦截 Claude
Code 的任意委派，因此它是可静态检查的生成内容契约，而不是平台层强制注入保证。真实验收观察
主 Agent 是否按提示传递；不把单次模型行为当作确定性结构测试。

## 8. 资源布局

### 8.1 Python distribution 内置资源

Canonical 内容和 Adapter 包装按以下布局分离：

```text
project_execution_rules/resources/
├── catalog.yaml
├── rules/
│   ├── core/
│   └── profiles/
├── skills/
├── agents/
├── adapters/
│   ├── codex/
│   └── claude/
├── schemas/
└── templates/
```

Canonical Skill/Agent 正文位于公共目录；Adapter 目录只保存平台专有模板或固定资源。所有内容
继续随 wheel/sdist 离线发布，不在运行时从网络下载。

### 8.2 Claude 系统级安装

Windows 上的用户 Home 解析后，Claude Adapter 安装：

```text
~/.claude/
├── rules/
├── skills/
│   └── <skill-id>/SKILL.md
└── agents/
    └── <agent-id>.md
```

只安装用户在 `install` 中选择的 Catalog 集合及其引用闭包。引用闭包中的 Skill/Agent 是必需
依赖，不能只安装 Rule 后留下悬空调用。

不创建、不修改 `~/.claude/CLAUDE.md`。已存在的同名非托管资源是冲突，任何安装或更新都不得
覆盖。

Claude Rules 和 Skills 官方支持 symlink，但本设计不以 symlink 或 junction 作为全局安装
前提。系统级 Claude 资源使用由 manifest 校验的普通托管文件。Agent symlink 和 Windows
junction 未获官方兼容承诺，不使用。

### 8.3 Claude 项目初始化

```text
project/
├── .rules/
│   └── ruleset.yaml
└── .claude/
    ├── CLAUDE.md
    ├── rules/
    │   └── <rule-id>.project.md
    ├── skills/
    └── agents/
```

Claude Code 不提供 `.override.md` 的原生合并语义；用户级 Base Rule 与项目 Rule 会同时进入
上下文，项目 Rule 后加载但不是确定性的字段覆盖。为避免暗示平台会自动合并，本设计把 Claude
项目差异称为 **Project Rule Extension**，文件名使用 `<rule-id>.project.md`。CLI 与 Rule Set
内部仍可把它归类为 Adapter Override，以保持跨 Adapter 生命周期术语一致。

Project Rule Extension 只允许追加项目事实、缩小适用范围和补充执行细节，不得否定 Base
`MUST` 或允许 Base `MUST NOT` 禁止的行为。Checker 可机械检查来源、路径范围和结构；自然
语言是否发生冲突由只读语义审查发现，不宣称 Claude Code 原生完成合并。

规则：

- `.claude/CLAUDE.md` 只在不存在时初始化；存在时不修改；
- 初始化完成后 `.claude/CLAUDE.md` 完全归项目所有，不纳入托管 checksum；
- `.claude/CLAUDE.md` 说明本项目使用的元规范、Project Rule Extension 位置、Rule→Skill→Agent 模型及扩展方式；
- `.claude/rules/` 只保存 Claude Project Rule Extension，不复制全局 Base；
- `.claude/skills/` 与 `.claude/agents/` 可在本次本机初始化中创建为空，但空目录不是 Git
  持久化不变量；重新克隆后目录缺失仍是健康状态，项目首次新增资源时再创建；
- 不为 Git 跟踪生成占位 Skill、Agent、`.gitkeep` 或模板；
- Claude Project Rule Extension 与 Codex Override 相互独立，允许平台差异；
- 每个 Project Rule Extension 都是普通项目文件，不得是 symlink、junction 或其他 reparse point；
- 只有用户在 `init` 中选择且存在具体项目差异的 Rule 才创建 Project Rule Extension，禁止批量生成无内容文件；
- init 不复制、链接或修改全局 Claude Base。

### 8.4 Claude 资源优先级与命名冲突

Claude Code 对三类资源采用不同规则：

| 资源 | 用户级与项目级关系 | 本设计策略 |
|---|---|---|
| Rules | 用户级先加载、项目级后加载；内容共同进入上下文 | 项目只使用 `<base-id>.project.md` 扩展，不复制同名 Base |
| Skills | 用户级 Skill 优先于同名项目 Skill | 项目 Skill 不得与已安装用户 Skill 同名；Checker 报遮蔽冲突 |
| Agents | 项目 Agent 优先于同名用户 Agent | 项目同名 Agent 视为显式项目替换；Checker 报告替换关系 |

Rule、Skill、Agent 各自使用独立逻辑 ID 命名空间。项目自有 Skill/Agent 必须在各自递归目录树
内 ID 唯一。对 Skill，同名用户级资源会使项目资源无法成为实际解析目标，因此作为 error；对
Agent，项目替换是 Claude Code 的官方优先级行为，但 status/check 必须明确显示，避免静默替换。

项目 Rule Extension 使用不同文件名和 Rule ID 元数据关联 Base；它不是与 Base 同名的副本。

### 8.5 Codex 项目布局

Codex 保留现有 `AGENTS.md`、`.rules/` Base 链接和 Codex Override 语义。Codex 所需项目 Base
链接属于该 Adapter 的必要项目结构，不因 Claude 使用全局原生发现机制而删除。

## 9. Rule Set

Rule Set 破坏式升级为多 Adapter schema，不读取旧的 `adapter: codex`。这是项目尚无外部用户时
有意进行的主版本重构：旧项目得到明确 `compatibility_error`，不会静默迁移。所谓“Codex
完整回归”仅指使用 v2 Rule Set 新初始化后的 Codex 资源和生命周期行为，不包含旧 v1 项目的
读取兼容。

```yaml
schema_version: 2
rules_version: 1.0.0
adapters:
  - codex
  - claude
profile: python

domains:
  core:
    - security
    - testing
  profile:
    - python

overrides:
  codex:
    - testing
    - python
  claude:
    - testing
```

约束：

- `adapters` 非空、去重并按 Registry 规范顺序序列化；
- 项目只能启用已完成系统级安装的 Adapter；
- `domains` 表示项目选择的元规范集合；
- `overrides` 按 Adapter 分组，允许平台差异；
- Override ID 必须属于 `domains`；
- Rule Set 不保存本机 Home、CLI 路径、凭据、PID 或绝对路径；
- 旧 schema 直接报告 `compatibility_error`，不自动迁移。

当项目启用多个 Adapter 时，所选 Rule 及其依赖必须在每个 Adapter 的系统级安装中可用。若各
Adapter 安装集合不同，项目可选集合是它们的交集；请求不可用对象时停止并提示先运行
`install --adapter ...` 补齐资源。

## 10. CLI 交互与自动化

### 10.1 Adapter 参数

所有需要选择 Adapter 的命令支持可重复参数：

```text
--adapter codex --adapter claude
```

交互模式使用多选，可选择一个或多个 Adapter。JSON 输出使用规范顺序的数组。

### 10.2 `install`

`install` 负责系统级资源安装：

1. 选择 Adapter；
2. 选择 Core Rules 和 Profile；
3. 展开 Rule 引用的 Skill/Agent 闭包；
4. 为每个 Adapter 分别展示 ChangePlan；
5. 分别授权、备份、应用和验证；
6. 写入 Adapter 独立 manifest。

未显式传 `--adapter` 时：

- 检测到 `codex`，选择 Codex；
- 检测到 `claude`，选择 Claude；
- 同时检测到两者，选择两者；
- 两者都未检测到：交互模式显示多选，非交互模式返回 usage/environment 错误并要求显式选择。

CLI 检测只用于首次选择，不作为后续生命周期的期望状态来源。

### 10.3 `init`

`init` 只创建项目级结构，不安装或补齐系统级资源：

1. 读取每个 Adapter 的系统级 manifest；
2. 交互模式从已安装 Adapter 中多选项目子集；
3. 非交互未传 `--adapter` 时选择全部已安装 Adapter；
4. 选择项目适用的 Core Rules、Profile 和需创建的 Adapter 独立 Override；
5. 只生成项目 ChangePlan；
6. 授权后应用并运行确定性 `check`。

选择未安装 Adapter 或系统级引用闭包不完整时，init 停止并提示先运行 install。init 不因检测到
CLI 而隐式修改 `~/.codex` 或 `~/.claude`。

### 10.4 其他命令

- `status`：分别显示 Adapter 安装状态、项目启用状态和漂移摘要；
- `check`：默认检查 Rule Set 中所有 Adapter，可用 `--adapter` 缩小范围；
- `doctor`：检查所有注册 Adapter 的 CLI 可发现性，并区分“未安装资源”和“CLI 不可用”；
- `update/repair/rollback/uninstall`：支持 Adapter 多选，默认处理当前范围内全部已安装/启用 Adapter；
- `review`：本次继续使用现有 Codex Reviewer，不因安装 Claude Adapter 自动切换或增加 Claude 调用。

## 11. 托管清单与所有权

### 11.1 Adapter 独立 manifest

系统级清单固定为：

```text
%LOCALAPPDATA%/ProjectExecutionRules/
├── managed-user-codex.json
└── managed-user-claude.json
```

manifest 使用固定 schema：

```json
{
  "schema_version": 2,
  "adapter": "claude",
  "resource_version": "1.0.0",
  "selection": {
    "rules": ["security", "testing"],
    "skills": ["testing"],
    "agents": ["rules-reviewer"]
  },
  "entries": [
    {
      "logical_path": "rules/security.md",
      "kind": "rule",
      "sha256": "<64 lowercase hex characters>"
    }
  ]
}
```

约束：

- `schema_version` 固定为 2；
- `adapter` 必须与文件名、路径根和当前 Adapter 一致；
- `selection` 数组去重并按 Catalog 规范顺序序列化；
- `logical_path` 相对于该 Adapter Home，必须是规范 POSIX 相对路径，禁止绝对路径和 `..`；
- `kind` 为 `rule|skill|agent`；
- `sha256` 为 64 位小写十六进制；
- entries 按 `logical_path` 排序且不得重复；
- manifest 本身属于对应 Adapter 事务，但不得列入自身 entries。

不得继续使用一个无法区分 Adapter 所有权的 `managed-user.json`。

### 11.2 系统级托管资源

只有 manifest 明确记录且当前身份与 checksum 可验证的文件才能被覆盖、修复、回滚或删除。
同名非托管文件、symlink、junction、目录逃逸或 checksum 不符都必须停止并报告冲突/漂移，
不得静默接管。

### 11.3 项目所有资源

以下内容不使用 Base checksum 强制恢复：

- `.claude/CLAUDE.md`；
- Claude Project Rule Extension；
- Codex Override；
- 项目后来新增的 Rules、Skills 和 Agents。

Rule Set 可以记录预期存在和项目选择，但 `repair` 不能用内置模板覆盖这些文件。缺失时只报告
结构问题，除非用户明确重新执行对应初始化操作。

## 12. 生命周期与事务

### 12.1 独立边界

每个 Adapter 拥有独立：

- ChangePlan；
- 用户授权；
- backup；
- transaction record；
- manifest；
- update、repair、rollback 和 uninstall 目标集合。

选择多个 Adapter 时，CLI 可以连续执行多个独立事务，但不得把它们伪装成一个原子事务。
前一个成功、后一个失败时必须如实报告部分成功状态，不得回滚用户未授权回滚的另一个 Adapter。

### 12.2 更新

update 比较内置 Catalog、Adapter 渲染结果和对应 manifest：

- 新增或变更的系统级 Base 可以在授权后更新；
- 删除的 Base 只在托管身份可验证时删除；
- 项目指南和 Override 只报告潜在影响，不修改；
- Rule→Skill→Agent 引用变化必须在预览中显示；
- 一个 Adapter 的更新不得触碰另一个 Adapter 的 manifest 或资源。

### 12.3 修复

repair 只修复能够由 Adapter manifest 和内置资源确定恢复内容的系统级托管文件，以及工具仍
拥有的必要项目结构。对已转为项目所有的 `.claude/CLAUDE.md`、Override 和后续生长内容，
repair 只报告，不覆盖。

### 12.4 回滚

rollback 只恢复指定 Adapter 的已完成/失败事务。事务记录必须包含 Adapter ID；目标身份、
Adapter、路径根或恢复边界不一致时拒绝执行。

### 12.5 卸载

Claude uninstall 只删除 `managed-user-claude.json` 明确记录且身份可验证的系统级 Base 文件
和该 manifest。它永久保留：

- 项目 `.claude/`；
- `.claude/CLAUDE.md`；
- Claude Project Rule Extension；
- 项目新增 Rules、Skills 和 Agents；
- Codex 的任何资源和 manifest。

空的系统级父目录只有在属于 Adapter Home、删除后不会影响非托管内容时才可清理；不以清理
空目录为完成条件。

### 12.6 全局资源与登记项目

registry 继续记录 CLI 已初始化项目的规范路径，并增加项目启用的 Adapter 集合。全局 update 和
uninstall 在计划阶段扫描仍可访问的登记项目：

- update 预览列出受资源变化影响的项目和 Rule ID；
- 存在仍启用目标 Adapter 的登记项目时，uninstall 默认拒绝；
- 用户必须显式传递 `--force` 才能卸载，并在预览中逐项看到将失去 Base 的项目；
- 不可访问或已移动的登记项目作为 warning 展示，不自动删除登记记录；
- 强制卸载仍不得删除任何项目内容；
- 无法保证发现未登记项目，CLI 必须在强制确认中明确这一限制。

项目数量不改变事务边界：全局 Base 仍由一个 Adapter 用户级事务更新，项目只接受影响报告，
不在全局 update/uninstall 中被修改。

## 13. Checker 与 Doctor

### 13.1 确定性 Checker

系统级检查：

- manifest schema、Adapter ID 和路径根；
- 托管文件存在性、普通文件身份和 checksum；
- Claude Rule frontmatter；
- Skill 目录与 `SKILL.md`；
- Agent Markdown 和必需 frontmatter；
- 安装选择与 Rule→Skill→Agent 引用闭包；
- task/explicit Rule 启动预算；
- 非托管同名冲突。

项目级检查：

- Rule Set v2 schema；
- 项目 Adapter 均已系统级安装；
- 所选 Rule 和依赖在每个 Adapter 可用；
- `.claude/CLAUDE.md` 是否存在，但不检查其 checksum；
- Claude Project Rule Extension 是否是普通项目文件；
- Project Rule Extension 是否属于所选 Rule，且没有扩大 `paths` 或机械性否定 Base 边界；
- Claude 与 Codex Override 分组是否一致；
- `.claude/skills/`、`.claude/agents/` 中项目自有资源只在目录存在时检查格式、重复 ID、
  用户 Skill 遮蔽和项目 Agent 替换关系；目录在没有项目资源时缺失仍为健康；

Checker 不启动 Claude，不执行 Rule 中的命令，不判断目标项目是否已经实现测试或 CI。

### 13.2 Doctor

Doctor 检查：

- `claude` 与 `codex` 命令可发现性，包括 Windows `.cmd` wrapper；
- CLI 版本输出是否可执行；
- Adapter Home 和项目目录权限；
- Adapter manifest 状态；
- 未完成事务；
- Git 仓库状态；
- Claude Code 官方不承诺的 junction/Agent symlink 是否被错误用作托管资源。

`claude doctor` 是可选的只读安装诊断证据，不是 Rules/Skills/Agents 的完整 validator。命令不可用
时 doctor 报告环境问题，但静态 check 仍可独立运行。

## 14. 错误处理

沿用现有稳定错误类别，并增加 Adapter 证据：

- `usage_error`：Adapter 参数为空、重复选择或非交互无法推断；
- `environment_error`：所选 CLI 不可发现、目录不可写或命令 wrapper 无法执行；
- `structure_error`：Catalog 引用缺失、Rule Set v2 无效、Claude frontmatter 或布局错误；
- `conflict_error`：目标存在同名非托管资源或路径身份不安全；
- `compatibility_error`：旧 Rule Set schema、未注册 Adapter 或不受支持的资源组合；
- `transaction_error`：指定 Adapter 的备份、应用、验证或恢复失败；
- `review_error`：继续只用于现有 Codex Reviewer。

JSON 错误至少包含：

```text
code
message
adapter（适用时）
evidence
remediation
```

多 Adapter 操作必须按 Adapter 返回独立结果；部分成功不可被总结果掩盖。

## 15. 安全与非侵入边界

- 不读取 `.env`、凭据或 Claude/Codex 登录令牌；
- 不修改 `~/.claude/CLAUDE.md`；
- 不修改 Claude/Codex settings、permissions 或 hooks；
- 不从 Rule/Skill Markdown 提取并执行命令；
- 不运行目标项目测试、构建、CI 或外部服务；
- 不覆盖非托管同名资源；
- 不把 junction 当作 Claude 官方兼容机制；
- 不通过项目文件修改系统级 Base；
- 删除前验证 Adapter、manifest、路径根和 checksum；
- 项目初始化内容一旦创建即归项目所有；
- Rule/Skill/Agent 是行为指导，不宣称构成不可绕过的安全边界。

## 16. 测试策略

### 16.1 单元测试

- Adapter Registry 和规范顺序；
- 多 Adapter 参数归一化；
- CLI 自动检测和未检测回退；
- Catalog 三类对象解析；
- WHEN/MUST/MUST NOT 结构；
- Rule→Skill→Agent 引用闭包与循环；
- Rule Set v2 解析和旧 schema 拒绝；
- Claude Rule frontmatter 渲染；
- Claude Skill/Agent frontmatter 渲染；
- task/explicit 精简 Rule 预算；
- Agent Skill 预加载和 Rule Brief 生成；
- Adapter 独立 manifest 和路径根验证。

### 16.2 Fixture 测试

至少覆盖：

- 仅 Codex、仅 Claude、Codex+Claude；
- 两个 CLI 都存在、只存在一个、均不存在；
- Adapter 已安装集合与项目选择的交集；
- 缺失 Skill、缺失 Agent、自引用和委派环；
- 非托管 `~/.claude/rules|skills|agents` 同名冲突；
- 已存在 `.claude/CLAUDE.md` 时 init 不修改；
- 仅有具体差异时创建 Adapter 独立 Override；
- 项目自有 Skill/Agent 不被 repair 或 uninstall 修改；
- Claude manifest 漂移不影响 Codex manifest；
- 一个 Adapter 事务成功、另一个失败时的部分成功报告；
- rollback 不能跨 Adapter；
- uninstall Claude 后项目 `.claude/` 完整保留。

### 16.3 Windows 集成测试

- `claude.cmd` 与 `codex.cmd` 发现；
- 系统级 Claude 普通文件安装；
- 多 Adapter 独立授权和事务；
- Claude 项目初始化；
- update、repair、rollback、uninstall；
- 非托管冲突保护；
- wheel/sdist 包含 Catalog、Canonical Skill/Agent 和两个 Adapter 资源；
- 现有 Codex Windows workflow 完整回归。

自动测试不依赖真实外部服务或付费模型调用。

### 16.4 真实 Claude Code CLI 验收

首个支持基线固定为 Claude Code `2.1.220`（本设计调研与本机验收版本）或更高版本。后续若
官方资源机制发生破坏性变化，必须提高基线并记录兼容矩阵，不能用“latest”代替版本证据。
验收记录必须包含 Claude Code 版本、Windows 版本、安装来源和是否已登录。

在目标环境中人工记录：

1. 静态发现检查：记录 `claude --version`、`claude doctor`、`/context` 和 `/skills`，确认
   资源来源、目录和解析结果；
2. 路径场景：在全新会话读取固定 fixture 的匹配文件，使用 `/context` 观察 `paths` Rule；
3. task 场景：使用固定提示词观察 Rule 是否指导加载对应 Skill；
4. explicit 场景：使用一个普通任务和一个显式命令分别观察不会自动进入、能够手动进入；
5. 委派场景：使用固定提示词观察 custom Agent 的预加载 Skill 和 Rule Brief；
6. Override 场景：确认 Project Rule Extension 与系统级 Base 均被加载，且 Base 未被项目修改；
7. 每个模型行为场景在全新会话重复 3 次，记录原始会话观察；3 次中至少 2 次符合期望才记为
   通过，否则标记为行为兼容失败并保留证据；
8. 静态发现失败一律失败，不得用模型行为偶然成功抵消。

`/context`、`/skills` 是会话内命令，因此真实验收不伪装成普通非交互 shell validator。
模型是否遵循 Rule、自动调用 Skill 或产生委派属于行为观察，不被描述为 Claude Code 的确定性
加载保证。

## 17. 验收标准

本设计完成实现后必须满足：

1. Codex 与 Claude 可以单选或多选安装；
2. `install` 只安装系统级资源，`init` 只创建项目结构；
3. Claude 全局安装包含所选 Rules 及其 Skill/Agent 引用闭包；
4. 不创建或修改 `~/.claude/CLAUDE.md`；
5. 项目 `.claude/CLAUDE.md` 只初始化一次，后续 update/repair 不覆盖；
6. Claude Project Rule Extension 与 Codex Override 独立；
7. Rule Set 使用非空 `adapters` 列表并拒绝旧 schema；
8. 每个 Adapter 具有独立 manifest、事务、回滚和卸载边界；
9. Claude uninstall 只删除系统级托管 Base，保留全部项目生长内容；
10. Rule 的 WHEN/MUST/MUST NOT 和结构化 Skill/Agent 引用可机械检查；
11. task/explicit Rule 保持精简，执行细节不复制进 Rule；
12. Agent 固定且允许模型调用的 Skill 使用预加载；委派型 Rule 包含 Rule Brief 提示结构，
    真实 CLI 验收将其作为行为观察而非平台强保证；
13. 未安装依赖、悬空引用和非托管冲突会停止而不是静默降级；
14. 自动测试覆盖多 Adapter 和 Windows 生命周期；
15. 真实 Claude Code 验收证明 Rules、Skills、Agents 和项目指南可被发现；
16. 现有 Codex 行为通过完整回归；
17. 不生成目标项目测试、CI、业务配置或 hooks/permissions。

## 18. 后续扩展边界

未来可以独立设计：

- Claude Code Reviewer Adapter；
- 项目级自定义 Rule/Skill/Agent 创建命令；
- 可选的 permissions/hooks 硬约束层；
- 其他 Agent 平台 Adapter；
- 团队级资源 Registry 和签名发布；
- 自动化 Claude Code 端到端验收 Harness。

实现此设计时必须同步更新 `README.md`、`docs/CODEMAPS.md`、源码导航文档、CLI 帮助和测试
索引，使其从“仅 Codex”转为准确的多 Adapter 说明；在实现合入前，本文件描述目标设计，
现有 README/CODEMAPS 仍描述当前已交付行为。

这些能力不能以空实现、占位字段或假兼容分支进入本次交付。
