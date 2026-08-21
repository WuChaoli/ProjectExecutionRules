---
name: git
description: Apply Git state, staging, and history safety during Git tasks.
---

# Git Skill

## Steps
1. Run `git status --short` and inspect the branch and remote before changes.
2. Read the relevant files before editing; preserve unrelated user changes.
3. Run `git diff` and inspect the exact staged scope before committing.
4. Use only authorized, precise targets; never use history-rewriting or destructive reset commands without explicit authorization.

## Checklist
- [ ] Current branch, worktree, and staged files confirmed.
- [ ] Only task-scoped files are staged.
- [ ] Diff and tests were checked before commit.

## Output
Report the changed scope, verification commands and results, and any unverified boundary.
