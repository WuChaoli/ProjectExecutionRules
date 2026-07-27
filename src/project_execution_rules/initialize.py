from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from project_execution_rules.detection import ProjectFacts
from project_execution_rules.doctor import probe_symlink_capability
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.managed import (
    ManagedManifest,
    has_reparse_ancestor,
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


def _expected_manifest_entries(
    adapter: AdapterId,
    selection: object,
) -> dict[str, str]:
    from project_execution_rules.managed import ManagedSelection

    selected = selection
    if not isinstance(selected, ManagedSelection):
        raise TypeError("selection must be ManagedSelection")
    if adapter is AdapterId.CLAUDE:
        return {
            **{f"rules/{item}.md": "rule" for item in selected.rules},
            **{f"skills/{item}/SKILL.md": "skill" for item in selected.skills},
            **{f"agents/{item}.md": "agent" for item in selected.agents},
        }
    return {
        **{f".agents/rules/{item}-rules.md": "rule" for item in selected.rules},
        ".agents/rules/catalog.yaml": "rule",
        ".agents/rules/review-report.schema.json": "rule",
        **{f".codex/skills/{item}/SKILL.md": "skill" for item in selected.skills},
        **{f".codex/agents/{item}.toml": "agent" for item in selected.agents},
    }


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
            remediation=f"Run `project-rules install --adapter {adapter.value}` first.",
        )
    manifest = ManagedManifest.load(manifest_path, expected_adapter=adapter)
    catalog = load_builtin_catalog()
    if manifest.resource_version != catalog.rules_version:
        raise ProjectRulesError(
            "USER_ADAPTER_CLOSURE_MISMATCH",
            f"installed Adapter version does not match the Catalog: {adapter.value}",
            evidence={
                "adapter": adapter.value,
                "installed": manifest.resource_version,
                "required": catalog.rules_version,
            },
            remediation=f"Run `project-rules install --adapter {adapter.value}`.",
        )
    required = resolve_catalog_selection(
        catalog,
        selection.core_domains + catalog.profiles["python"],
        adapter=adapter,
    )
    selected = manifest.selection
    try:
        installed_closure = resolve_catalog_selection(
            catalog,
            selected.rules,
            adapter=adapter,
        )
    except ValueError as error:
        raise ProjectRulesError(
            "USER_ADAPTER_CLOSURE_MISMATCH",
            f"installed Adapter selection is not a Catalog closure: {adapter.value}",
            evidence={"adapter": adapter.value, "error": str(error)},
            remediation=f"Run `project-rules install --adapter {adapter.value}`.",
        ) from error
    expected_selection = (
        set(installed_closure.rules),
        set(installed_closure.skills),
        set(installed_closure.agents),
    )
    actual_selection = (set(selected.rules), set(selected.skills), set(selected.agents))
    expected_entries = _expected_manifest_entries(adapter, selected)
    entries = {entry.logical_path: entry for entry in manifest.entries}
    if expected_selection != actual_selection or {
        path: entry.kind for path, entry in entries.items()
    } != expected_entries:
        raise ProjectRulesError(
            "USER_ADAPTER_CLOSURE_MISMATCH",
            f"installed Adapter manifest is not the exact Catalog closure: {adapter.value}",
            evidence={"adapter": adapter.value},
            remediation=f"Run `project-rules install --adapter {adapter.value}`.",
        )
    if not (
        set(required.rules) <= set(selected.rules)
        and set(required.skills) <= set(selected.skills)
        and set(required.agents) <= set(selected.agents)
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


def compose_project_changes(
    root: Path,
    plans: tuple[tuple[AdapterId, ChangePlan], ...],
) -> tuple[Change, ...]:
    resolved_root = root.resolve()
    lexical_root = Path(os.path.abspath(root))
    reserved = lexical_root / ".rules" / "ruleset.yaml"
    changes: list[Change] = []
    owners: dict[Path, tuple[AdapterId, Change]] = {}
    for adapter, plan in plans:
        for change in plan.changes:
            candidate = Path(os.path.abspath(change.target))
            try:
                candidate.relative_to(lexical_root)
            except ValueError as error:
                raise ProjectRulesError(
                    "ADAPTER_PROJECT_CONTRACT",
                    f"Adapter planned a target outside the project: {change.target}",
                    evidence={"adapter": adapter.value, "target": str(change.target)},
                ) from error
            if candidate == reserved:
                raise ProjectRulesError(
                    "ADAPTER_PROJECT_CONTRACT",
                    "Adapter planned the orchestrator-reserved Rule Set target",
                    evidence={"adapter": adapter.value, "target": str(change.target)},
                )
            if has_reparse_ancestor(candidate.parent, root=lexical_root):
                raise ProjectRulesError(
                    "ADAPTER_PROJECT_CONTRACT",
                    f"Adapter planned a target through an unsafe project path: {change.target}",
                    evidence={"adapter": adapter.value, "target": str(change.target)},
                )
            canonical_parent = candidate.parent.resolve(strict=False)
            try:
                canonical_parent.relative_to(resolved_root)
            except ValueError as error:
                raise ProjectRulesError(
                    "ADAPTER_PROJECT_CONTRACT",
                    f"Adapter planned a target outside the project: {change.target}",
                    evidence={"adapter": adapter.value, "target": str(change.target)},
                ) from error
            safe_target = canonical_parent / candidate.name
            normalized = Change(
                action=change.action,
                target=safe_target,
                content=change.content,
                link_target=change.link_target,
            )
            previous = owners.get(safe_target)
            if previous is not None:
                previous_adapter, previous_change = previous
                if previous_change != normalized:
                    raise ProjectRulesError(
                        "ADAPTER_PROJECT_COLLISION",
                        f"Adapters plan conflicting project changes: {safe_target}",
                        evidence={
                            "target": str(safe_target),
                            "adapters": [previous_adapter.value, adapter.value],
                        },
                    )
                continue
            owners[safe_target] = (adapter, normalized)
            changes.append(normalized)
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
    resolved_root = root.resolve()
    resolved_facts = replace(facts, root=resolved_root)
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
                resolved_root,
                resolved_facts,
                selection,
                paths,
                verify_user_install=False,
            ),
        )
        for adapter in selected_adapters
    )
    changes = list(compose_project_changes(resolved_root, adapter_plans))
    ruleset_target = resolved_root / ".rules" / "ruleset.yaml"
    if has_reparse_ancestor(ruleset_target.parent, root=resolved_root):
        raise ProjectRulesError(
            "ADAPTER_PROJECT_CONTRACT",
            "shared Rule Set target uses an unsafe project path",
            evidence={"target": str(ruleset_target)},
        )
    ruleset = Change(
        action="write",
        target=ruleset_target,
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
    resolved_root = root.resolve()
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
        resolved_root,
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
        _default_stage(resolved_root, staged)
    else:
        stage_files(staged)
    transaction_id = transaction.transaction_id
    transaction.cleanup()
    return OperationReport(
        changed=True,
        transaction_id=transaction_id,
        changes=plan.changes,
    )
