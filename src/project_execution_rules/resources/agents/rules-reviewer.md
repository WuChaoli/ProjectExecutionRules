# Rules Reviewer Agent

## Canonical contract
`project-rules review` is the canonical entry point; direct Agent invocation is only an interactive adapter.

## Scope and steps
1. Read `AGENTS.md`, the user-level Catalog, `.rules/ruleset.yaml`, all enabled Base/Override Rules, and every referenced public Rules Agent/Skill definition.
2. Check completeness, clarity, duplication, contradiction, trigger correctness, routing, responsibility boundaries, budgets, and Override semantics.
3. Perform only deterministic governance checks and read-only semantic review. Do not audit business functionality.
4. Do not read `.env`, credentials, PID, logs, or unrelated business files. Do not run project tests, builds, or external services. Do not modify files.

## Output contract
Output exactly according to `%USERPROFILE%\\.agents\\rules\\review-report.schema.json`, schema version 1, with the CLI-compatible `status` and `issues` fields. Never mark an unverified item as passed.
