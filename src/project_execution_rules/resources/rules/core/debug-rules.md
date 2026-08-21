# Debug Rules

## WHEN

- `DBG-001`：先收集可复现症状、错误文本和最近变化，再提出根因假设。

## MUST

- `DBG-002`：一次验证一个假设，优先定位根因而不是叠加补丁。
- `DBG-003`：诊断请求不自动授权修复或扩大副作用范围。
- Invoke the Catalog-declared `debug` Skill for the task workflow。

## MUST

- `DBG-004`：修复必须通过原始复现路径和回归测试验证。

## MUST NOT

日志与 Trace 设计由 Observability Rules 管理。
