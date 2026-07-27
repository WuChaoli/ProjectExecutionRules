# Task 6 实施报告：Claude Project Scaffold and Project Ownership

## 状态

已在用户指定基线 `06617a0` 上完成 Task 6。未实现 Task 7 Checker/Doctor 重设计或 Task 9 CLI 选择。

## TDD 证据

1. 先新增 Claude scaffold/ownership 与 Adapter composition 测试，覆盖缺失 manifest、guide 初始化与保留、非空 Project Rule Extensions、无 Base copy/link、共享 Rule Set、碰撞、Claude-only 无 symlink 探测、staging 与 init 不隐式 install。
2. RED：`uv run pytest tests/test_claude_adapter.py tests/test_initialize.py -v` 得到目标能力失败；主要失败为 Claude project plan 为空、`ProjectSelection.adapters` 缺失、wrapper 仅支持 Codex、未校验 manifest。
3. GREEN：实现 Adapter-composed project plan、Claude scaffold、共享 Rule Set、闭包校验、碰撞检测和按计划 symlink probe 后，focused 集合通过。
4. 补充损坏 manifest 缺少 selected entry 的闭包测试，先确认 `DID NOT RAISE` RED，再校验 selection、entries 和 checksum closure，回归测试转 GREEN。

## 实施内容

- `ProjectSelection` 记录 selected adapters；`plan_project_init` 按 Registry 顺序组合各 Adapter project plan。
- selected Adapter 必须存在 matching manifest v2，并覆盖所需 Rule/Skill/Agent selection、entries 与 checksum；init 不安装或修复用户级资源。
- Claude 仅在缺失时初始化 `.claude/CLAUDE.md`，既有 guide（含 symlink）不覆盖。
- Claude 仅为有项目事实的 selected override 生成 `.claude/rules/<rule-id>.project.md`；不创建空 extension、skills/agents 空目录，也不复制或链接 Claude Base Rules/Skills/Agents。
- `.rules/ruleset.yaml` 由组合层唯一生成，记录 selected adapters 和 Adapter-grouped overrides。
- project plan 目标按确定顺序去重；不同 Adapter 对同一 target 的不同 action/content 触发 `ADAPTER_PROJECT_COLLISION`。
- symlink capability 仅在实际 plan 含 symlink 时探测；Claude-only init 不依赖 Windows Developer Mode。
- staging 仅包含项目 guide、共享 Rule Set 与 Project Rule Extensions/Overrides，不包含 empty dirs 或 Base links。
- 项目生成内容保持项目所有权，不写入 Adapter managed manifest。

## 验证摘要

- Focused + Windows workflow：`29 passed`
- Full pytest：`153 passed`
- Ruff：`All checks passed!`
- Full Pyright：`0 errors, 0 warnings, 0 informations`
- Diff check：通过

## Concerns

- Task 6 只负责初始化与 project ownership；现有 Checker/Doctor 尚未按多 Adapter 重设计，留给 Task 7。
- CLI 多 Adapter 选择未接入，留给 Task 9；当前调用方可通过 `ProjectSelection.adapters` 使用组合能力。
