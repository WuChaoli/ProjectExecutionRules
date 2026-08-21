# Task 4 实施报告：Codex Adapter Migration and Rule Set v2

## 状态

已在要求的基线 `97af6e4` 之上完成 Task 4。未实现 Task 5 Claude 资源。

## TDD 证据

1. 先新增 `tests/test_rulesets.py` 与真实 `CodexAdapter` detect/install/project-plan 契约测试，并替换恒真 `Path` 断言。
2. RED：`uv run pytest tests/test_rulesets.py tests/test_adapters.py tests/test_install.py tests/test_initialize.py tests/test_checker.py -v` 在收集期因 `project_execution_rules.rulesets` 缺失失败，符合预期。
3. 为 Catalog domain membership 再单独新增测试；RED 为“DID NOT RAISE”，随后补充最小验证转 GREEN。
4. Fix round 1 继续先补三组回归测试：完整 Skill/Agent 闭包、Rule domain 分组、preview 单一规划真源；分别观察到 manifest entry 缺失、未抛错及 Adapter 参数缺失的 RED，再做最小修复。
5. GREEN：focused 测试、全量测试与静态质量门均通过。

## 实施内容

- 新增 `rulesets.py`：Rule Set v2 唯一 parser/renderer；严格拒绝非 schema 2、v1、未知字段、空/重复/乱序 Adapter、未知 Rule domain、未按 Adapter 分组或越界的 Override。
- `RuleSet` 改为多 Adapter 和 Adapter 分组 Override 模型。
- 新增并注册 `CodexAdapter`：实现 CLI detect、用户级资源/manifest 规划、项目 Base symlink、Override、`AGENTS.md`、`.gitignore` 和 Rule Set v2 规划。
- `CodexAdapter` 的选中 Skill/Agent 现在全部生成真实资源：优先使用 Codex-specific 包装，缺失时读取 Catalog canonical 文件；两者均不存在则返回稳定结构错误，不再静默跳过。
- Rule Set v2 额外强制 `domains.core` 仅包含 Catalog core Rule，`domains.profile` 仅包含所选 Profile 声明的 Rule。
- `initialize.py` 仅保留薄 wrapper；preview 通过 `verify_user_install=False` context 委托同一个 `CodexAdapter` 规划实现，不再复制项目计划逻辑。
- Checker、Doctor 和 lifecycle consumer 统一读取 Rule Set v2；v1 以 `RULESET_SCHEMA_INCOMPATIBLE` 拒绝，不提供兼容迁移。
- 更新 Rule Set/AGENTS 模板及现有 v1 fixtures。

## 验证摘要

- Focused：`39 passed`
- Adapter + Rule Set：`21 passed`
- Full pytest：`132 passed, 1 warning`
- Ruff：`All checks passed!`
- Full Pyright：`0 errors, 0 warnings, 0 informations`
- Diff check：通过

## Concerns

- 全量 pytest 仍有 1 个既有 Windows warning：`tests/test_commands.py::test_run_command_resolves_windows_command_wrapper_from_path` 的 subprocess reader 在本机代码页输出上触发 UTF-8 decode warning；不影响 132 个测试通过，且不属于 Task 4 变更范围。
- `resources/templates/*.j2` 当前仍是打包模板契约；运行时使用确定性 Python renderer，未为 Task 4 引入额外模板引擎路径。
