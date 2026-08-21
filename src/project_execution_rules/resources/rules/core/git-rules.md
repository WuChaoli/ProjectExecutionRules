# Git Rules

## WHEN

- `GIT-001`：分支、remote、工作树和已暂存内容必须通过 Git 当前状态确认。
- Invoke the Catalog-declared `git` Skill for branch, commit, merge, and worktree tasks.
- Task flow `git` Skill is required for branch, commit, merge, and worktree tasks.

## MUST

- `GIT-002`：只暂存任务范围内的文件，不回退用户已有修改。
- `GIT-003`：禁止未经授权改写历史或执行破坏性重置。
- `GIT-004`：提交前运行 diff 检查并确认暂存范围。
- Invoke the Catalog-declared `git` Skill for the task workflow.

## MUST NOT

PR 和 CI 门禁分别由 Pull Request Rules 与 CI/CD Rules 管理。
