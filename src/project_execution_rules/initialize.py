from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from project_execution_rules.catalog import load_builtin_catalog
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
    from project_execution_rules.rendering import (
        render_agents,
        render_python_override,
        render_ruleset,
    )

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
    if verify_user_install:
        from project_execution_rules.adapters import get_adapter

        adapter_plan = get_adapter(AdapterId.CODEX).plan_project_init(
            root,
            facts,
            selection,
            paths,
        )
        return ChangePlan(scope="project", changes=adapter_plan.changes)

    # 旧 orchestration 的 dry-run 会同时展示待安装用户资源和项目计划，因此只在
    # 该预览路径临时跳过 Base 存在性检查，不改变 Adapter 的正式 init 契约。
    catalog = load_builtin_catalog()
    domains = selection.core_domains + catalog.profiles["python"]
    for domain in domains:
        if domain not in catalog.rules:
            raise ProjectRulesError("RULE_UNKNOWN", f"unknown Rule domain: {domain}")
    rules_dir = root.resolve() / ".rules"
    changes = [
        Change(
            action="symlink",
            target=rules_dir / f"{domain}-rules.md",
            link_target=paths.rules_home / f"{domain}-rules.md",
        )
        for domain in domains
    ]
    for domain in selection.override_domains:
        if domain != "python":
            raise ProjectRulesError(
                "OVERRIDE_UNSUPPORTED",
                f"no real project override renderer exists for {domain}",
            )
        changes.append(
            Change(
                action="write",
                target=rules_dir / "python-rules.override.md",
                content=render_python_override(facts).encode(),
            )
        )
    changes.extend(
        (
            Change(
                action="write",
                target=rules_dir / "ruleset.yaml",
                content=render_ruleset(selection, adapters=adapters).encode(),
            ),
            Change(
                action="write",
                target=root.resolve() / "AGENTS.md",
                content=render_agents(selection).encode(),
            ),
            Change(
                action="write",
                target=root.resolve() / ".gitignore",
                content=append_codex_ignore(
                    (root.resolve() / ".gitignore").read_text(encoding="utf-8")
                    if (root.resolve() / ".gitignore").is_file()
                    else "",
                    domains,
                ).encode(),
            ),
        )
    )
    return ChangePlan(
        scope="project",
        changes=tuple(change for change in changes if project_change_required(change)),
    )


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
