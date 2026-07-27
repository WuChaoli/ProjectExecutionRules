from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from project_execution_rules.catalog import load_builtin_catalog
from project_execution_rules.detection import ProjectFacts
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.managed import sha256_bytes
from project_execution_rules.models import Change, ChangePlan, OperationReport
from project_execution_rules.paths import UserPaths
from project_execution_rules.transactions import FileTransaction


@dataclass(frozen=True, slots=True)
class ProjectSelection:
    core_domains: tuple[str, ...]
    override_domains: tuple[str, ...] = ()


def _append_ignore(existing: str, domains: tuple[str, ...]) -> str:
    lines = existing.splitlines()
    for domain in domains:
        entry = f".rules/{domain}-rules.md"
        if entry not in lines:
            lines.append(entry)
    return "\n".join(lines).rstrip() + "\n"


def plan_project_init(
    root: Path,
    facts: ProjectFacts,
    selection: ProjectSelection,
    paths: UserPaths,
) -> ChangePlan:
    from project_execution_rules.rendering import (
        render_agents,
        render_python_override,
        render_ruleset,
    )

    resolved = root.resolve()
    if not facts.is_git:
        raise ProjectRulesError(
            "GIT_REPOSITORY_MISSING",
            "project initialization requires a Git repository",
        )
    if facts.profile != "python":
        raise ProjectRulesError(
            "PROFILE_UNSUPPORTED",
            "the first release supports Python projects only",
        )
    catalog = load_builtin_catalog()
    domains = selection.core_domains + catalog.profiles["python"]
    for domain in domains:
        if domain not in catalog.rules:
            raise ProjectRulesError("RULE_UNKNOWN", f"unknown Rule domain: {domain}")
        if not (paths.rules_home / f"{domain}-rules.md").is_file():
            raise ProjectRulesError(
                "USER_RULE_MISSING",
                f"user Rule is not installed: {domain}",
            )
    changes: list[Change] = []
    rules_dir = resolved / ".rules"
    for domain in domains:
        changes.append(
            Change(
                action="symlink",
                target=rules_dir / f"{domain}-rules.md",
                link_target=paths.rules_home / f"{domain}-rules.md",
            )
        )
    for domain in selection.override_domains:
        if domain != "python":
            raise ProjectRulesError(
                "OVERRIDE_UNSUPPORTED",
                f"no real project override renderer exists for {domain}",
            )
        content = render_python_override(facts).encode()
        changes.append(
            Change(
                action="write",
                target=rules_dir / "python-rules.override.md",
                content=content,
            )
        )
    changes.extend(
        [
            Change(
                action="write",
                target=rules_dir / "ruleset.yaml",
                content=render_ruleset(selection).encode(),
            ),
            Change(
                action="write",
                target=resolved / "AGENTS.md",
                content=render_agents(selection).encode(),
            ),
            Change(
                action="write",
                target=resolved / ".gitignore",
                content=_append_ignore(
                    (resolved / ".gitignore").read_text(encoding="utf-8")
                    if (resolved / ".gitignore").is_file()
                    else "",
                    domains,
                ).encode(),
            ),
        ]
    )
    return ChangePlan(scope="project", changes=tuple(changes))


def _default_stage(root: Path, files: tuple[Path, ...]) -> None:
    relative = [str(path.relative_to(root)) for path in files]
    result = subprocess.run(
        ["git", "add", "--", *relative],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ProjectRulesError(
            "GIT_STAGE_FAILED",
            "failed to stage generated governance files",
            evidence={"stderr": result.stderr},
        )


def initialize_project(
    plan: ChangePlan,
    root: Path,
    paths: UserPaths,
    *,
    confirmed: bool,
    symlink_factory: Callable[[str, Path], None] = os.symlink,
    link_verifier: Callable[[Path, Path], bool] | None = None,
    stage_files: Callable[[tuple[Path, ...]], None] | None = None,
) -> OperationReport:
    if not confirmed:
        return OperationReport(changed=False, transaction_id=None, changes=())
    verifier = link_verifier or (
        lambda link, target: link.is_symlink() and link.resolve() == target.resolve()
    )
    transaction = FileTransaction(
        paths.state_home,
        root,
        symlink_factory=symlink_factory,
    )
    for change in plan.changes:
        if change.action == "write":
            transaction.plan_write(change.target, change.content)
        elif change.action == "symlink" and change.link_target is not None:
            transaction.plan_symlink(change.target, change.link_target)
        else:
            raise ProjectRulesError(
                "CHANGE_INVALID",
                f"unsupported project change: {change.action}",
            )

    def verify() -> bool:
        for change in plan.changes:
            if change.action == "write":
                if not change.target.is_file():
                    return False
                if sha256_bytes(change.target.read_bytes()) != sha256_bytes(change.content):
                    return False
            elif change.link_target is None or not verifier(change.target, change.link_target):
                return False
        return True

    transaction.apply(verify)
    staged = tuple(
        change.target
        for change in plan.changes
        if change.action == "write"
        and (
            change.target.name in {"AGENTS.md", ".gitignore", "ruleset.yaml"}
            or change.target.name.endswith(".override.md")
        )
    )
    (stage_files or (lambda files: _default_stage(root, files)))(staged)
    transaction_id = transaction.transaction_id
    transaction.cleanup()
    return OperationReport(
        changed=True,
        transaction_id=transaction_id,
        changes=plan.changes,
    )
