from __future__ import annotations

import json
import os
from pathlib import Path

from project_execution_rules.catalog import resource_root
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.managed import ManagedManifest, sha256_bytes
from project_execution_rules.models import (
    Change,
    ChangePlan,
    OperationReport,
    RuleCatalog,
)
from project_execution_rules.paths import UserPaths
from project_execution_rules.transactions import FileTransaction


def _managed_hashes(paths: UserPaths) -> dict[str, str]:
    manifest_path = paths.state_home / "managed-user.json"
    if not manifest_path.is_file():
        return {}
    manifest = ManagedManifest.load(manifest_path)
    return {entry.logical_path: entry.sha256 for entry in manifest.entries}


def _resource_changes(paths: UserPaths, catalog: RuleCatalog) -> list[Change]:
    root = resource_root()
    rules_root = root.joinpath("rules")
    changes: list[Change] = []
    for domain, definition in catalog.rules.items():
        source = rules_root.joinpath(definition.file)
        changes.append(
            Change(
                action="write",
                target=paths.rules_home / f"{domain}-rules.md",
                content=source.read_bytes(),
            )
        )
    changes.extend(
        [
            Change(
                action="write",
                target=paths.rules_home / "catalog.yaml",
                content=root.joinpath("catalog.yaml").read_bytes(),
            ),
            Change(
                action="write",
                target=paths.codex_agents / "rules-reviewer.toml",
                content=root.joinpath("adapters/codex/agents/rules-reviewer.toml").read_bytes(),
            ),
            Change(
                action="write",
                target=paths.codex_skills / "rules-reviewer" / "SKILL.md",
                content=root.joinpath("adapters/codex/skills/rules-reviewer/SKILL.md").read_bytes(),
            ),
        ]
    )
    for skill_name in ("agent-governance", "tool-governance"):
        changes.append(
            Change(
                action="write",
                target=paths.codex_skills / skill_name / "SKILL.md",
                content=root.joinpath(f"adapters/codex/skills/{skill_name}/SKILL.md").read_bytes(),
            )
        )
    return changes


def _plan_user_resources(
    paths: UserPaths,
    catalog: RuleCatalog,
    *,
    allow_managed_drift: bool,
) -> ChangePlan:
    managed = _managed_hashes(paths)
    changes: list[Change] = []
    entries: list[dict[str, str]] = []
    for change in _resource_changes(paths, catalog):
        logical = change.target.relative_to(paths.home).as_posix()
        desired_hash = sha256_bytes(change.content)
        if change.target.is_file():
            current_hash = sha256_bytes(change.target.read_bytes())
            if current_hash == desired_hash:
                entries.append({"logical_path": logical, "kind": "file", "sha256": desired_hash})
                continue
            if managed.get(logical) != current_hash and not (
                allow_managed_drift and logical in managed
            ):
                raise ProjectRulesError(
                    "NON_MANAGED_CONFLICT",
                    f"refusing to overwrite non-managed file: {change.target}",
                    evidence={"target": str(change.target)},
                    remediation="Move or rename the conflicting file, then retry.",
                )
        changes.append(change)
        entries.append({"logical_path": logical, "kind": "file", "sha256": desired_hash})
    manifest_content = (
        json.dumps(
            {
                "resource_version": catalog.rules_version,
                "entries": entries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode()
    manifest_path = paths.state_home / "managed-user.json"
    if not manifest_path.is_file() or manifest_path.read_bytes() != manifest_content:
        changes.append(
            Change(
                action="write",
                target=manifest_path,
                content=manifest_content,
            )
        )
    return ChangePlan(scope="user", changes=tuple(changes))


def plan_user_install(paths: UserPaths, catalog: RuleCatalog) -> ChangePlan:
    return _plan_user_resources(paths, catalog, allow_managed_drift=False)


def plan_user_repair(paths: UserPaths, catalog: RuleCatalog) -> ChangePlan:
    return _plan_user_resources(paths, catalog, allow_managed_drift=True)


def install_user_resources(
    plan: ChangePlan,
    paths: UserPaths,
    *,
    confirmed: bool,
) -> OperationReport:
    if not confirmed:
        return OperationReport(changed=False, transaction_id=None, changes=())
    if not plan.changes:
        return OperationReport(changed=False, transaction_id=None, changes=())
    common_root = Path(os.path.commonpath([paths.home, paths.state_home]))
    transaction = FileTransaction(paths.state_home, common_root)
    for change in plan.changes:
        transaction.plan_write(change.target, change.content)

    def verify() -> bool:
        return all(
            change.target.is_file()
            and sha256_bytes(change.target.read_bytes()) == sha256_bytes(change.content)
            for change in plan.changes
        )

    transaction.apply(verify)
    transaction_id = transaction.transaction_id
    transaction.cleanup()
    return OperationReport(
        changed=True,
        transaction_id=transaction_id,
        changes=plan.changes,
    )
