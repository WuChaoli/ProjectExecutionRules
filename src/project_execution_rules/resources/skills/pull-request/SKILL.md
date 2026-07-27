---
name: pull-request
description: Apply pull request review, authorization, and merge gates.
---

# Pull Request Skill

## Steps
1. Read the current pull request, template, requested reviewers, checks, and unresolved review threads from the hosting platform.
2. Summarize scope, validation evidence, risk, and unconfirmed boundaries.
3. Confirm authorization before creating, updating, merging, or closing a pull request.
4. Before merge, re-read required checks and unresolved reviews.

## Tools
Use the repository hosting CLI/API read operations for current PR state; use write operations only after explicit authorization.

## Checklist
- [ ] Scope and evidence are in the description.
- [ ] Required checks are current and passing.
- [ ] No unresolved review remains.
- [ ] Merge or other write action is authorized.

## Output
Return the current PR state, evidence, risks, unresolved items, and whether the requested operation is authorized.
