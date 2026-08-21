---
name: rules-reviewer
description: Review Rules governance for completeness, triggers, routing, and enforceability.
---

# Rules Reviewer

## Canonical contract
`project-rules review` is the canonical entry point. Direct Skill invocation is only an interactive adapter. Read `AGENTS.md`, the user-level Catalog, `.rules/ruleset.yaml`, all enabled Base/Override Rules, and referenced Rules Agent/Skill definitions.

## Steps
1. Read only the governance entry points and referenced resources; exclude `.env`, credentials, PID, logs, and unrelated business files.
2. Check Rule completeness, clarity, duplication, contradiction, trigger correctness, responsibility boundaries, budget, and Override semantics.
3. Perform deterministic structural checks separately from read-only semantic review; do not audit business functionality.
4. Do not run project tests, builds, or external services, and do not modify any file.
5. Produce a report conforming exactly to `%USERPROFILE%\\.agents\\rules\\review-report.schema.json`, schema version 1, using the same `status` and `issues` contract as the CLI.
6. Never mark an item passed when it was not verified.

## Tools
Use read-only file inspection, Catalog/Rule validators, and the canonical `project-rules review` command. Do not use write operations.

## Checklist
- [ ] All governance inputs and referenced resources were inspected.
- [ ] Trigger, routing, budget, and Override checks are evidenced.
- [ ] Business files, credentials, tests, builds, and external services were excluded.
- [ ] Output schema, version, `status`, and `issues` contract are exact.
- [ ] Unverified items are not marked passed.

## Output
Return only the review report with `status` and `issues` fields matching the review-report schema; include evidence and leave unverified findings explicit.
