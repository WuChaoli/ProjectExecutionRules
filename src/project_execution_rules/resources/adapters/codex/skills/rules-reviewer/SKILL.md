---
name: rules-reviewer
description: Review Project Execution Rules for completeness, clarity, trigger correctness, routing, and enforceability without auditing business functionality.
---

# Rules Reviewer

只读审查当前 Rules 治理层。

1. 读取 `AGENTS.md`、用户级 Catalog、`.rules/ruleset.yaml`、Rule Set 中全部启用的
   Base/Override，以及被这些入口引用的 Rules Agent/Skill 定义。
2. 检查规则是否完整、明确、无重复和无矛盾。
3. 检查 Trigger、职责边界、预算和 Override 语义。
4. 不读取 `.env`、凭据、PID、日志或无关业务文件。
5. 不运行项目测试、构建或外部服务。
6. 不修改任何文件。
7. `project-rules review` 是 canonical 主入口；直接调用本 Skill 只作为交互适配。
8. 输出必须符合 `%USERPROFILE%\.agents\rules\review-report.schema.json`
   （schema version 1），与 CLI 使用相同的 `status` 和 `issues` 契约。
9. 未验证事项不得标为通过。
