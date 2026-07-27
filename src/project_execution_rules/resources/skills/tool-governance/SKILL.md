---
name: tool-governance
description: Explicitly govern Skill, MCP, LSP, CLI, or other tool rules.
---

# Tool Governance

## Steps
1. Read project `AGENTS.md`, the applicable Tool Rule, and referenced Skill, MCP, LSP, CLI, or tool definitions.
2. Check trigger conditions, source/version, permissions, health checks, lifecycle, failure degradation, and cleanup entry points.
3. Verify discovery, invocation, expected failure, recovery, and authorization boundaries without changing files.
4. Record only evidence from current installation and configuration.

## Tools
Use read-only configuration inspection, tool discovery, and bounded health checks; do not audit business functionality, alter tool configuration, or invoke uncontrolled external services.

## Checklist
- [ ] Trigger and permission boundaries are explicit.
- [ ] Health, lifecycle, failure, and cleanup paths are defined.
- [ ] Discovery and invocation evidence is current.
- [ ] Configuration changes remain separately authorized.

## Output
Report tool source/version, trigger and permission findings, health and recovery evidence, and unverified behavior.
