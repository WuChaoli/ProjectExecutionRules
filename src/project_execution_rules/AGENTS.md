# project_execution_rules/ — Rules 生命周期实现

## 模块职责

该包提供 Catalog、项目探测、确定性规划、显式路径事务、检查诊断、只读 Reviewer
和 Typer CLI。它只治理 Rules 基础设施，不执行项目测试、构建、外部服务或业务审计。

## 文件索引

| 文件 | 职责 | 关键入口 |
|---|---|---|
| `cli.py` | 交互和非交互命令编排 | `app` |
| `commands.py` | 跨平台解析并执行外部 CLI | `run_command` |
| `models.py` | 不可变领域模型和状态 | `ChangePlan`、`CheckReport` |
| `catalog.py` | 加载并校验内置 Rule Catalog | `load_builtin_catalog` |
| `detection.py` | 静态探测 Git/Python 项目事实 | `detect_project` |
| `rendering.py` | 渲染 AGENTS、Rule Set 和 Override | `render_agents` |
| `install.py` | 用户级资源计划与事务安装 | `plan_user_install` |
| `initialize.py` | 项目级初始化计划与事务 | `plan_project_init` |
| `checker.py` | checksum、链接、Trigger、路由检查 | `check_project` |
| `doctor.py` | 环境与基础设施探测 | `run_doctor` |
| `reviewer.py` | 隔离目录中的 Codex Rules 审查 | `review_rules` |
| `lifecycle.py` | update、repair、rollback、uninstall | `plan_repair` |
| `transactions.py` | 精确授权根事务与恢复复验 | `FileTransaction` |
| `managed.py` | 托管 manifest 和 SHA-256 | `ManagedManifest` |
| `status.py` | 项目状态摘要 | `get_project_status` |
| `resources/` | 内置 Rules、Schema、Agent 和 Skill | `catalog.yaml` |

## 模块内数据流

`cli` 读取 Catalog 和项目事实，生成 `ChangePlan`；用户确认后，install、initialize
或 lifecycle 将精确变更交给 `FileTransaction`。事务完成内容/链接验证后才清理备份。
checker 和 doctor 始终从真实文件重新计算状态。reviewer 先复制允许的治理文件到临时
目录，再启动只读 Codex。

## 局部规则

- 新行为先写失败测试，至少覆盖一个真实失败边界。
- 不直接在 CLI handler 中写文件；统一进入服务层和事务引擎。
- 不把用户级与项目级 Change 放入同一个 `FileTransaction`。
- 路径校验必须解析父链但不跟随 leaf symlink。
- 新增 adapter 资源时同步 package data、安装 manifest、Reviewer 隔离输入和 wheel
  资源测试。
- 变更 CLI/公共数据结构时同步 `docs/CODEMAPS.md` 和 `README.md`。
