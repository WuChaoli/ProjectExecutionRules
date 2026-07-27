# Task 5 实施报告：Claude Adapter Global Resources

## 状态

已在要求的基线 `1abb234` 之上完成 Task 5。未实现 Task 6 项目脚手架。

## TDD 证据

1. 先新增 Claude Adapter 安装与渲染测试，覆盖依赖闭包、Rule frontmatter、task/explicit 骨架、user-only Skill、Agent 字段与预加载、普通文件、确定性、manifest 闭包一致性、非托管冲突和 `~/.claude/CLAUDE.md` 排除。
2. RED：`uv run pytest tests/test_claude_adapter.py tests/test_install.py tests/test_resources.py -v` 得到 `8 failed, 15 passed`；失败原因是 `_PlaceholderAdapter`、空安装计划和缺失三个模板，符合预期。
3. GREEN：实现真实 `ClaudeAdapter`、三个 Jinja 模板和通用 managed install-plan builder 后，focused 测试通过。
4. 审查发现空 Skill 预加载会渲染 YAML `null`；先新增回归测试并确认 `assert None == []` RED，再将模板修复为 `skills: []`，单测转 GREEN。

## 实施内容

- 新增并注册真实 `ClaudeAdapter`，只规划 `~/.claude/rules`、`skills/<id>/SKILL.md`、`agents/<id>.md` 和 `managed-user-claude.json`。
- Rule 只在 `activation: paths` 时输出原生 `paths` frontmatter；其余 Rule 保持无 frontmatter 的 `WHEN / MUST / MUST NOT` 常驻骨架。
- Skill 保留 `name`、`description`，仅 `invocation: user` 输出 `disable-model-invocation: true`。
- Agent 输出必需的 `name`、`description`、`skills`；预加载列表只保留 `invocation: model` 的 Catalog Skill，空列表稳定渲染为 `[]`。
- 从 Codex Adapter 提取通用 `build_managed_install_plan`，Claude/Codex 共用相同 checksum、unsafe path、symlink/reparse 和非托管冲突语义。
- Claude selection、manifest selection、manifest entries 和资源 targets 均由同一闭包生成；不创建 symlink/junction，绝不规划 `~/.claude/CLAUDE.md`。
- 使用 `importlib.resources` 兼容的 Jinja loader，模板继续随 wheel/sdist 离线打包。

## 验证摘要

- Focused：`24 passed`
- Full pytest：`142 passed`
- Ruff：`All checks passed!`
- Full Pyright：`0 errors, 0 warnings, 0 informations`
- Diff check：通过

## Concerns

- Task 5 只提供 Adapter 级 global install plan；现有公共 `plan_user_install` 仍由后续多 Adapter 生命周期任务组合，目前继续默认 Codex，符合本任务不提前实现 Task 6+ 的边界。
- Agent description 当前由稳定的 Catalog ID 生成；Canonical Agent 模型尚无独立 description 字段。若后续元规范扩展 Agent description，应从 Catalog 消费而不是复制触发规则。
