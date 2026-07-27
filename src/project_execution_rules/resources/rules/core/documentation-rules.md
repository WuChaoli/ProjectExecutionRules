---
paths:
  - "**/*.md"
---

# Documentation Rules

## 事实来源

- `DOC-001`：文档必须与当前代码、配置、测试和 CI 一致。

## 执行规则

- `DOC-002`：入口文档保持简短，长背景、流程和计划进入对应 docs 目录。
- `DOC-003`：历史设计不得替代当前实现事实。

## 验证要求

- `DOC-004`：新增链接必须存在，命令示例必须与实际入口一致。

## 职责边界

Rule、Profile 和 Trigger 由 Catalog 管理；AGENTS 路由是由 Catalog 生成并检查的
Codex 适配视图。Agent Rules 只管理 Agent/Subagent 角色和协作边界。
