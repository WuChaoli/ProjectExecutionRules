---
name: agent-governance
description: Explicitly govern project Agent or Subagent rules.
---

# Agent Governance

## Steps
1. Read project `AGENTS.md`, the applicable Agent Rule, and any referenced Agent/Subagent definitions or overrides.
2. Check each role's responsibility, inputs, outputs, stopping conditions, and explicit non-responsibilities.
3. Check authorization, read/write boundaries, tool permissions, handoff ownership, and concurrency file ownership.
4. Verify definition syntax and, where authorized, a real invocation result; do not change files.

## Tools
Use read-only repository search and parser/validator commands. Do not run project tests or audit business functionality.

## Checklist
- [ ] Role contract is complete.
- [ ] Permissions and read/write boundaries are explicit.
- [ ] Handoffs and concurrent ownership are safe.
- [ ] Syntax and authorized invocation evidence are recorded.

## Output
Report verified role findings, boundary violations, and unverified checks without modifying the project.
