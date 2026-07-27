# Harness Rules

## WHEN

- `HAR-001`：Rules 治理状态必须由文件、加载链和实际检查输出证明。

## MUST

- `HAR-002`：结构检查只做确定性判断，语义 Review 必须只读。
- `HAR-003`：Rules 修复与业务功能审计必须保持职责隔离。
- Invoke the Catalog-declared `rules-reviewer` Skill and Agent for explicit rules-review commands。

## MUST

- `HAR-004`：变更后必须重新检查 Catalog、Rule Set、触发器、预算和托管状态。

## MUST NOT

首版 Harness 不运行项目测试，不评分业务项目成熟度。
