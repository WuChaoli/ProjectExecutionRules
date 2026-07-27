from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from project_execution_rules.detection import ProjectFacts
from project_execution_rules.doctor import probe_symlink_capability
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.managed import sha256_bytes
from project_execution_rules.models import AdapterId, Change, ChangePlan, OperationReport
from project_execution_rules.paths import UserPaths
from project_execution_rules.transactions import FileTransaction


@dataclass(frozen=True, slots=True)
class ProjectSelection:
    core_domains: tuple[str, ...]
    override_domains: tuple[str, ...] = ()


def append_codex_ignore(existing: str, domains: tuple[str, ...]) -> str:
    lines = existing.splitlines()
    for domain in domains:
        entry = f".rules/{domain}-rules.md"
        if entry not in lines:
            lines.append(entry)
    return "\n".join(lines).rstrip() + "\n"


def project_change_required(change: Change) -> bool:
    if change.action == "write":
        return (
            change.target.is_symlink()
            or not change.target.is_file()
            or change.target.read_bytes() != change.content
        )
    if change.action == "symlink" and change.link_target is not None:
        try:
            return not (
                change.target.is_symlink()
                and change.target.resolve() == change.link_target.resolve()
            )
        except OSError:
            return True
    return True


def plan_project_init(
    root: Path,
    facts: ProjectFacts,
    selection: ProjectSelection,
    paths: UserPaths,
    *,
    verify_user_install: bool = True,
    adapters: tuple[AdapterId, ...] = (AdapterId.CODEX,),
) -> ChangePlan:
    from project_execution_rules.adapters import get_adapter

    if adapters != (AdapterId.CODEX,):
        raise ProjectRulesError(
            "ADAPTER_UNSUPPORTED",
            "Codex is the only project Adapter implemented in Task 4",
        )
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
    adapter_plan = get_adapter(AdapterId.CODEX).plan_project_init(
        root,
        facts,
        selection,
        paths,
        verify_user_install=verify_user_install,
    )
    return ChangePlan(scope="project", changes=adapter_plan.changes)


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


def _actual_link_verifier(link: Path, target: Path) -> bool:
    return link.is_symlink() and link.resolve() == target.resolve()


def initialize_project(
    plan: ChangePlan,
    root: Path,
    paths: UserPaths,
    *,
    confirmed: bool,
    symlink_factory: Callable[[str, Path], None] = os.symlink,
    link_verifier: Callable[[Path, Path], bool] | None = None,
    stage_files: Callable[[tuple[Path, ...]], None] | None = None,
    symlink_probe: Callable[[], bool] | None = None,
) -> OperationReport:
    if not confirmed:
        return OperationReport(changed=False, transaction_id=None, changes=())
    if not plan.changes:
        return OperationReport(changed=False, transaction_id=None, changes=())
    probe = symlink_probe or (lambda: probe_symlink_capability(paths))
    if not probe():
        raise ProjectRulesError(
            "SYMLINK_UNAVAILABLE",
            "Windows symbolic link creation is unavailable",
            remediation="Enable Windows Developer Mode or grant link privileges.",
        )
    verifier = link_verifier or _actual_link_verifier
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
    if stage_files is None:
        _default_stage(root, staged)
    else:
        stage_files(staged)
    transaction_id = transaction.transaction_id
    transaction.cleanup()
    return OperationReport(
        changed=True,
        transaction_id=transaction_id,
        changes=plan.changes,
    )
