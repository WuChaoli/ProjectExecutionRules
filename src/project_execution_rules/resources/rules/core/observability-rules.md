# Observability Rules

## WHEN

- `OBS-001`：可观测能力必须从当前日志、Trace、指标和运行配置取证。

## MUST

- `OBS-002`：记录可定位失败的上下文，不记录凭据和敏感正文。
- `OBS-003`：性能结论必须基于测量，不得只凭代码形态推断。
- Invoke the Catalog-declared `observability` Skill for the task workflow。

## MUST

- `OBS-004`：声明可观察前必须验证信号能够产生、关联和读取。

## MUST NOT

业务正确性由项目测试负责，不由可观测信号替代。
