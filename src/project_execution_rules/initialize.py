from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from project_execution_rules.detection import ProjectFacts
from project_execution_rules.doctor import probe_symlink_capability
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.managed import (
    ManagedManifest,
    is_current_managed_file,
    sha256_bytes,
)
from project_execution_rules.models import AdapterId, Change, ChangePlan, OperationReport
from project_execution_rules.paths import UserPaths
from project_execution_rules.transactions import FileTransaction


@dataclass(frozen=True, slots=True)
class ProjectSelection:
    core_domains: tuple[str, ...]
    override_domains: tuple[str, ...] = ()
    adapters: tuple[AdapterId, ...] = (AdapterId.CODEX,)


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


def validate_user_install(
    adapter: AdapterId,
    selection: ProjectSelection,
    paths: UserPaths,
) -> None:
    from project_execution_rules.catalog import load_builtin_catalog
    from project_execution_rules.selection import resolve_catalog_selection

    manifest_path = paths.manifest_path(adapter)
    if not manifest_path.is_file():
        raise ProjectRulesError(
            "USER_ADAPTER_NOT_INSTALLED",
            f"selected Adapter is not installed: {adapter.value}",
            evidence={"adapter": adapter.value, "manifest": str(manifest_path)},
        )
    manifest = ManagedManifest.load(manifest_path, expected_adapter=adapter)
    catalog = load_builtin_catalog()
    required = resolve_catalog_selection(
        catalog,
        selection.core_domains + catalog.profiles["python"],
        adapter=adapter,
    )
    selected = manifest.selection
    entries = {entry.logical_path: entry for entry in manifest.entries}
    if adapter is AdapterId.CLAUDE:
        required_paths = {
            *(f"rules/{rule_id}.md" for rule_id in required.rules),
            *(f"skills/{skill_id}/SKILL.md" for skill_id in required.skills),
            *(f"agents/{agent_id}.md" for agent_id in required.agents),
        }
    else:
        required_paths = {
            *(f".agents/rules/{rule_id}-rules.md" for rule_id in required.rules),
            *(f".codex/skills/{skill_id}/SKILL.md" for skill_id in required.skills),
            *(f".codex/agents/{agent_id}.toml" for agent_id in required.agents),
        }
    if not (
        set(required.rules) <= set(selected.rules)
        and set(required.skills) <= set(selected.skills)
        and set(required.agents) <= set(selected.agents)
        and required_paths <= set(entries)
    ):
        raise ProjectRulesError(
            "USER_ADAPTER_CLOSURE_MISMATCH",
            f"installed Adapter closure does not cover project selection: {adapter.value}",
            evidence={"adapter": adapter.value},
        )
    adapter_home = paths.home if adapter is AdapterId.CODEX else paths.claude_home
    for entry in manifest.entries:
        target = adapter_home / entry.logical_path
        if not is_current_managed_file(
            target,
            expected_adapter=adapter,
            adapter_home=adapter_home,
            manifest_path=manifest_path,
        ):
            raise ProjectRulesError(
                "USER_ADAPTER_CLOSURE_MISMATCH",
                f"installed Adapter resource does not match its manifest: {adapter.value}",
                evidence={"adapter": adapter.value, "target": str(target)},
            )


def _compose_project_changes(
    plans: tuple[tuple[AdapterId, ChangePlan], ...],
) -> tuple[Change, ...]:
    changes: list[Change] = []
    owners: dict[Path, tuple[AdapterId, Change]] = {}
    for adapter, plan in plans:
        for change in plan.changes:
            previous = owners.get(change.target)
            if previous is not None:
                previous_adapter, previous_change = previous
                if previous_change != change:
                    raise ProjectRulesError(
                        "ADAPTER_PROJECT_COLLISION",
                        f"Adapters plan conflicting project changes: {change.target}",
                        evidence={
                            "target": str(change.target),
                            "adapters": [previous_adapter.value, adapter.value],
                        },
                    )
                continue
            owners[change.target] = (adapter, change)
            changes.append(change)
    return tuple(changes)


def plan_project_init(
    root: Path,
    facts: ProjectFacts,
    selection: ProjectSelection,
    paths: UserPaths,
    *,
    verify_user_install: bool = True,
    adapters: tuple[AdapterId, ...] | None = None,
) -> ChangePlan:
    from project_execution_rules.adapters import get_adapter, normalize_adapters
    from project_execution_rules.rendering import render_ruleset

    selected_adapters = normalize_adapters(adapters or selection.adapters)
    if not selected_adapters:
        raise ProjectRulesError("ADAPTER_REQUIRED", "at least one project Adapter is required")
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
        for adapter in selected_adapters:
            validate_user_install(adapter, selection, paths)
    adapter_plans = tuple(
        (
            adapter,
            get_adapter(adapter).plan_project_init(
                root,
                facts,
                selection,
                paths,
                verify_user_install=False,
            ),
        )
        for adapter in selected_adapters
    )
    changes = [
        change
        for change in _compose_project_changes(adapter_plans)
        if change.target != root.resolve() / ".rules" / "ruleset.yaml"
    ]
    ruleset = Change(
        action="write",
        target=root.resolve() / ".rules" / "ruleset.yaml",
        content=render_ruleset(selection, adapters=selected_adapters).encode(),
    )
    if project_change_required(ruleset):
        changes.append(ruleset)
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
    has_symlinks = any(change.action == "symlink" for change in plan.changes)
    if has_symlinks and not probe():
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
            change.target.name in {"AGENTS.md", "CLAUDE.md", "ruleset.yaml"}
            or change.target.name.endswith((".override.md", ".project.md"))
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
