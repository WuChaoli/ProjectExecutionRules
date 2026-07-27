# Repository Guide

## 事实来源与安全边界

- 当前行为以 `src/`、`tests/`、`pyproject.toml`、`uv.lock` 和实际 CLI 输出为准。
- 不读取或提交 `.env`、凭据、PID、日志、本机事务、备份和 review cache。
- 本项目只治理 Rules 基础设施；不得扩展为业务代码审计、项目测试或外部服务执行器。
- 文件写入必须保持用户级与项目级事务隔离，不覆盖无法确认归属的文件。

## 实现与验证

- Python 版本下限为 3.11，依赖和命令统一使用 `uv`。
- 新行为先写失败测试，再实现最小改动。
- 完整验证：
  `uv run ruff format --check src tests`、
  `uv run ruff check src tests`、
  `uv run pyright`、
  `uv run pytest -q` 和 `uv build`。
- 完成声明必须引用本轮真实命令输出；未执行的验证不得声称通过。

## 最小导航

- 产品边界和使用方式见 `README.md`。
- 跨模块关系、事务数据流和常见任务入口见 `docs/CODEMAPS.md`。
- Python 包内部导航见 `src/project_execution_rules/AGENTS.md`。
- 设计见 `docs/superpowers/specs/2026-07-27-project-execution-rules-design.md`。
- 实施与验收见
  `docs/superpowers/plans/2026-07-27-project-execution-rules-implementation.md`。
- Rule Catalog 和内置资源位于 `src/project_execution_rules/resources/`。
