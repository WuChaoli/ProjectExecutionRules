# Pull Request Rules

## WHEN

- `PR-001`：PR 状态、模板、Review 和检查结果必须从当前托管平台读取。

## MUST

- Invoke the Catalog-declared `pull-request` Skill for pull-request and pull-request-review tasks.
- Use the Catalog-declared `rules-reviewer` Agent for review-oriented PR flows.

：PR 描述必须说明范围、验证证据、风险和未确认边界。
- `PR-003`：未经授权不得创建、更新、合并或关闭 PR。

## MUST

- `PR-004`：合并前必须重新确认 required checks 和未解决 Review。
- Invoke the Catalog-declared `pull-request` Skill for pull-request and pull-request-review tasks.
- Use the Catalog-declared `rules-reviewer` Agent for review-oriented PR flows。

## MUST NOT

本地提交由 Git Rules 管理，流水线实现由 CI/CD Rules 管理。
