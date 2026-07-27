---
name: tool-governance
description: 显式治理 Skill、MCP、LSP、CLI 或其他工具规则时使用。
---

# Tool Governance

只读取项目 `AGENTS.md`、`.rules/tool-rules.md` 和存在的
`.rules/tool-rules.override.md`。检查工具触发、权限、生命周期和失败边界是否完整、
明确且可执行。不得审计业务功能、运行项目测试或修改业务代码。
