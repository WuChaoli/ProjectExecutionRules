from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import cast

from project_execution_rules.catalog import resource_root
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.initialize import ProjectSelection
from project_execution_rules.install import plan_user_install
from project_execution_rules.managed import (
    ManagedManifest,
    is_current_managed_file,
    is_safe_adapter_file,
    sha256_bytes,
)
from project_execution_rules.models import (
    AdapterId,
    Change,
    ChangePlan,
    OperationReport,
    RuleCatalog,
    RuleSet,
)
from project_execution_rules.paths import UserPaths
from project_execution_rules.rendering import render_agents
from project_execution_rules.rulesets import load_ruleset, render_ruleset
from project_execution_rules.transactions import FileTransaction, resolve_target_within_root
from project_execution_rules.yaml_utils import (
    as_mapping,
    as_object_tuple,
    as_string,
    as_string_tuple,
    load_mapping,
)

_RULE_ID = re.compile(r"`([A-Z][A-Z0-9]*(?:-OVR)?-\d{3})`")


def plan_update(paths: UserPaths, catalog: RuleCatalog) -> ChangePlan:
    return plan_user_install(paths, catalog)


def summarize_update(
    root: Path,
    paths: UserPaths,
    catalog: RuleCatalog,
) -> dict[str, object]:
    resource_rules = resource_root().joinpath("rules")
    added: list[str] = []
    modified: list[str] = []
    affected_files: list[str] = []
    desired_logical: set[str] = set()
    desired_ids: set[str] = set()
    installed_ids: set[str] = set()
    for domain, definition in catalog.rules.items():
        target = paths.rules_home / f"{domain}-rules.md"
        desired = resource_rules.joinpath(definition.file).read_bytes()
        logical = target.relative_to(paths.home).as_posix()
        desired_logical.add(logical)
        desired_ids.update(_RULE_ID.findall(desired.decode("utf-8")))
        if not target.is_file():
            added.append(domain)
            affected_files.append(str(target))
            continue
        current = target.read_bytes()
        installed_ids.update(_RULE_ID.findall(current.decode("utf-8")))
        if current != desired:
            modified.append(domain)
            affected_files.append(str(target))
    deprecated: list[str] = []
    manifest_path = paths.manifest_path(AdapterId.CODEX)
    from_version: str | None = None
    if manifest_path.is_file():
        manifest = ManagedManifest.load(
            manifest_path,
            expected_adapter=AdapterId.CODEX,
        )
        from_version = manifest.resource_version
        for entry in manifest.entries:
            if (
                entry.logical_path.startswith(".agents/rules/")
                and entry.logical_path.endswith("-rules.md")
                and entry.logical_path not in desired_logical
            ):
                deprecated.append(Path(entry.logical_path).stem.removesuffix("-rules"))
                affected_files.append(str(paths.home / entry.logical_path))
    trigger_changes: list[str] = []
    installed_catalog = paths.rules_home / "catalog.yaml"
    if installed_catalog.is_file():
        try:
            raw_catalog = load_mapping(
                installed_catalog.read_text(encoding="utf-8"),
                name="installed Catalog",
            )
            raw_rules = as_mapping(raw_catalog.get("rules", {}), name="installed rules")
            for domain, definition in catalog.rules.items():
                raw_rule = as_mapping(raw_rules.get(domain, {}), name=f"installed {domain}")
                installed_trigger = (
                    as_string(raw_rule.get("activation"), name=f"{domain} activation"),
                    as_string_tuple(raw_rule.get("paths", ()), name=f"{domain} paths"),
                    as_string_tuple(raw_rule.get("tasks", ()), name=f"{domain} tasks"),
                    as_string_tuple(raw_rule.get("commands", ()), name=f"{domain} commands"),
                )
                desired_trigger = (
                    definition.activation.value,
                    definition.paths,
                    definition.tasks,
                    definition.commands,
                )
                if installed_trigger != desired_trigger:
                    trigger_changes.append(domain)
        except (OSError, ValueError):
            trigger_changes = list(catalog.rules)
    changed_domains = set(added + modified + deprecated + trigger_changes)
    overrides = sorted(
        path.name.removesuffix("-rules.override.md")
        for path in (root.resolve() / ".rules").glob("*-rules.override.md")
        if path.name.removesuffix("-rules.override.md") in changed_domains
    )
    schema_compatible = True
    ruleset_path = root.resolve() / ".rules" / "ruleset.yaml"
    if ruleset_path.is_file():
        try:
            load_ruleset(ruleset_path)
        except ProjectRulesError:
            schema_compatible = False
    return {
        "rules_version": {
            "from": from_version,
            "to": catalog.rules_version,
        },
        "rules": {
            "added": sorted(added),
            "modified": sorted(modified),
            "deprecated": sorted(deprecated),
        },
        "rule_ids": {
            "added": sorted(desired_ids - installed_ids),
            "deprecated": sorted(installed_ids - desired_ids),
        },
        "trigger_changes": sorted(trigger_changes),
        "override_impact": overrides,
        "affected_files": sorted(set(affected_files)),
        "schema_compatible": schema_compatible,
    }


def plan_project_update(root: Path, catalog: RuleCatalog) -> ChangePlan:
    ruleset = load_ruleset(root.resolve() / ".rules" / "ruleset.yaml")
    if ruleset.rules_version == catalog.rules_version:
        return ChangePlan(scope="project", changes=())
    updated = RuleSet(
        schema_version=ruleset.schema_version,
        rules_version=catalog.rules_version,
        adapters=ruleset.adapters,
        profile=ruleset.profile,
        core_domains=ruleset.core_domains,
        profile_domains=ruleset.profile_domains,
        overrides=ruleset.overrides,
    )
    content = render_ruleset(updated).encode()
    return ChangePlan(
        scope="project",
        changes=(
            Change(
                action="write",
                target=root.resolve() / ".rules" / "ruleset.yaml",
                content=content,
            ),
        ),
    )


def _load_ruleset(root: Path) -> RuleSet:
    path = root / ".rules" / "ruleset.yaml"
    if not path.is_file():
        raise ProjectRulesError(
            "RULESET_MISSING",
            "project Rule Set does not exist",
        )
    return load_ruleset(path)


def _actual_link_verifier(link: Path, target: Path) -> bool:
    return link.is_symlink() and link.resolve() == target.resolve()


def plan_repair(
    root: Path,
    paths: UserPaths,
    *,
    link_verifier: Callable[[Path, Path], bool] = _actual_link_verifier,
) -> ChangePlan:
    resolved = root.resolve()
    ruleset = _load_ruleset(resolved)
    core = ruleset.core_domains
    profile = ruleset.profile_domains
    changes: list[Change] = []
    for domain in core + profile:
        link = resolved / ".rules" / f"{domain}-rules.md"
        target = paths.rules_home / f"{domain}-rules.md"
        if not link_verifier(link, target):
            changes.append(
                Change(
                    action="symlink",
                    target=link,
                    link_target=target,
                )
            )
    desired_agents = render_agents(ProjectSelection(core_domains=core)).encode()
    agents = resolved / "AGENTS.md"
    if not agents.is_file() or agents.read_bytes() != desired_agents:
        changes.append(Change(action="write", target=agents, content=desired_agents))
    return ChangePlan(scope="project", changes=tuple(changes))


def plan_uninstall(
    root: Path,
    paths: UserPaths,
    *,
    include_user: bool,
) -> ChangePlan:
    resolved = root.resolve()
    ruleset = _load_ruleset(resolved)
    domains = ruleset.domains
    changes: list[Change] = []
    for domain in domains:
        link = resolved / ".rules" / f"{domain}-rules.md"
        target = paths.rules_home / f"{domain}-rules.md"
        if not link.exists() and not link.is_symlink():
            continue
        if not link.is_symlink() or link.resolve() != target.resolve():
            raise ProjectRulesError(
                "NON_MANAGED_CONFLICT",
                f"refusing to remove non-managed Rule target: {link}",
            )
        changes.append(Change(action="remove", target=link))
    changes.append(Change(action="remove", target=resolved / ".rules" / "ruleset.yaml"))
    agents = resolved / "AGENTS.md"
    desired_agents = render_agents(ProjectSelection(core_domains=ruleset.core_domains))
    if agents.is_file() and agents.read_text(encoding="utf-8") == desired_agents:
        changes.append(Change(action="remove", target=agents))
    if include_user:
        raise ProjectRulesError(
            "TRANSACTION_SCOPE_MIXED",
            "user and project uninstall must use separate transactions",
        )
    return ChangePlan(scope="project", changes=tuple(changes))


def plan_user_uninstall(paths: UserPaths) -> ChangePlan:
    manifest_path = paths.manifest_path(AdapterId.CODEX)
    if not manifest_path.is_file():
        return ChangePlan(scope="user", changes=())
    manifest = ManagedManifest.load(
        manifest_path,
        expected_adapter=AdapterId.CODEX,
    )
    changes: list[Change] = []
    for entry in manifest.entries:
        target = paths.home / Path(entry.logical_path)
        if (
            is_safe_adapter_file(target, adapter_home=paths.home)
            and sha256_bytes(target.read_bytes()) == entry.sha256
        ):
            changes.append(Change(action="remove", target=target))
    changes.append(Change(action="remove", target=manifest_path))
    return ChangePlan(scope="user", changes=tuple(changes))


def apply_lifecycle_plan(
    plan: ChangePlan,
    root: Path,
    paths: UserPaths,
    *,
    confirmed: bool,
    symlink_factory: Callable[[str, Path], None] = os.symlink,
    link_verifier: Callable[[Path, Path], bool] | None = None,
) -> OperationReport:
    if not confirmed or not plan.changes:
        return OperationReport(changed=False, transaction_id=None, changes=())
    if plan.scope == "project":
        authorized_root = root.resolve()
        for change in plan.changes:
            if change.action == "symlink" and (
                change.link_target is None
                or not is_current_managed_file(
                    change.link_target,
                    expected_adapter=AdapterId.CODEX,
                    adapter_home=paths.home,
                    manifest_path=paths.manifest_path(AdapterId.CODEX),
                )
            ):
                raise ProjectRulesError(
                    "USER_RULE_MISSING",
                    f"cannot create a project link to a missing or drifted user Rule: "
                    f"{change.link_target}",
                )
    else:
        authorized_root = Path(os.path.commonpath([root, paths.home, paths.state_home]))
    transaction = FileTransaction(
        paths.state_home,
        authorized_root,
        adapter=AdapterId.CODEX if plan.scope == "user" else None,
        symlink_factory=symlink_factory,
    )
    for change in plan.changes:
        if change.action == "write":
            transaction.plan_write(change.target, change.content)
        elif change.action == "symlink" and change.link_target is not None:
            transaction.plan_symlink(change.target, change.link_target)
        elif change.action == "remove":
            transaction.plan_remove(change.target)
        else:
            raise ProjectRulesError(
                "CHANGE_INVALID",
                f"unsupported lifecycle change: {change.action}",
            )
    verifier = link_verifier or _actual_link_verifier

    def verify() -> bool:
        for change in plan.changes:
            if change.action == "remove" and (change.target.exists() or change.target.is_symlink()):
                return False
            if change.action == "write" and (
                not change.target.is_file()
                or sha256_bytes(change.target.read_bytes()) != sha256_bytes(change.content)
            ):
                return False
            if (
                change.action == "symlink"
                and change.link_target is not None
                and not verifier(change.target, change.link_target)
            ):
                return False
        return True

    transaction.apply(verify)
    transaction_id = transaction.transaction_id
    transaction.cleanup()
    return OperationReport(True, transaction_id, plan.changes)


def _validate_transaction_adapter(
    raw: dict[str, object],
    *,
    expected_adapter: AdapterId | str | None,
) -> None:
    if expected_adapter is None:
        return
    expected = AdapterId(expected_adapter)
    try:
        actual = AdapterId(as_string(raw["adapter"], name="transaction Adapter"))
    except (KeyError, TypeError, ValueError) as error:
        raise ProjectRulesError(
            "TRANSACTION_ADAPTER_INVALID",
            "transaction Adapter metadata is missing or invalid",
            evidence={"expected_adapter": expected.value},
        ) from error
    if actual is not expected:
        raise ProjectRulesError(
            "TRANSACTION_ADAPTER_MISMATCH",
            f"transaction belongs to Adapter {actual.value}, not {expected.value}",
            evidence={
                "expected_adapter": expected.value,
                "actual_adapter": actual.value,
            },
        )


def rollback_transaction(
    paths: UserPaths,
    transaction_id: str,
    *,
    expected_adapter: AdapterId | str | None = None,
) -> None:
    if not transaction_id or any(
        character not in "0123456789abcdef" for character in transaction_id
    ):
        raise ProjectRulesError(
            "TRANSACTION_ID_INVALID",
            f"transaction ID is invalid: {transaction_id}",
        )
    transaction_home = paths.transactions_home / transaction_id
    manifest_path = transaction_home / "manifest.json"
    if not manifest_path.is_file():
        raise ProjectRulesError(
            "TRANSACTION_MISSING",
            f"transaction does not exist: {transaction_id}",
        )
    raw = as_mapping(
        cast(object, json.loads(manifest_path.read_text(encoding="utf-8"))),
        name="transaction manifest",
    )
    _validate_transaction_adapter(raw, expected_adapter=expected_adapter)
    authorized_root = Path(as_string(raw["authorized_root"], name="authorized_root")).resolve()
    originals = as_object_tuple(raw.get("originals", ()), name="transaction originals")
    for original_value in reversed(originals):
        original = as_mapping(original_value, name="transaction original")
        try:
            logical_target = Path(as_string(original["target"], name="original target"))
            if logical_target.is_absolute() or ".." in logical_target.parts:
                raise ProjectRulesError(
                    "TRANSACTION_TARGET_INVALID",
                    f"transaction target is not relative: {logical_target}",
                )
            target = resolve_target_within_root(
                authorized_root / logical_target,
                authorized_root,
            )
        except ProjectRulesError as error:
            raise ProjectRulesError(
                "TRANSACTION_TARGET_INVALID",
                "transaction target is outside authorized root",
            ) from error
        if target.is_file() or target.is_symlink():
            target.unlink()
        elif target.exists():
            raise ProjectRulesError(
                "TRANSACTION_TARGET_UNSAFE",
                f"refusing to replace non-file target: {target}",
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        kind = as_string(original["kind"], name="original kind")
        if kind == "file":
            backup = Path(as_string(original["backup"], name="backup path"))
            try:
                backup = resolve_target_within_root(
                    backup,
                    paths.backups_home / transaction_id,
                )
            except ProjectRulesError as error:
                raise ProjectRulesError(
                    "TRANSACTION_BACKUP_INVALID",
                    "transaction backup path is outside its backup directory",
                ) from error
            if backup.is_symlink() or not backup.is_file():
                raise ProjectRulesError(
                    "TRANSACTION_BACKUP_INVALID",
                    f"transaction backup is not a regular file: {backup}",
                )
            target.write_bytes(backup.read_bytes())
        elif kind == "symlink":
            os.symlink(
                as_string(original["link_target"], name="link target"),
                target,
            )
        elif kind != "missing":
            raise ProjectRulesError(
                "TRANSACTION_KIND_INVALID",
                f"unknown transaction original kind: {kind}",
            )
    for original_value in originals:
        original = as_mapping(original_value, name="transaction original")
        logical_target = Path(as_string(original["target"], name="original target"))
        target = resolve_target_within_root(
            authorized_root / logical_target,
            authorized_root,
        )
        kind = as_string(original["kind"], name="original kind")
        if kind == "file":
            backup = resolve_target_within_root(
                Path(as_string(original["backup"], name="backup path")),
                paths.backups_home / transaction_id,
            )
            restored = (
                not target.is_symlink()
                and target.is_file()
                and not backup.is_symlink()
                and backup.is_file()
                and target.read_bytes() == backup.read_bytes()
            )
        elif kind == "symlink":
            restored = target.is_symlink() and os.readlink(target) == as_string(
                original["link_target"],
                name="link target",
            )
        else:
            restored = not target.exists() and not target.is_symlink()
        if not restored:
            raise ProjectRulesError(
                "ROLLBACK_VERIFY_FAILED",
                f"rollback verification failed: {target}",
                remediation="Transaction evidence and backups were preserved.",
            )
    backup_home = paths.backups_home / transaction_id
    for path in (transaction_home, backup_home):
        if path.exists():
            path.resolve().relative_to(paths.state_home.resolve())
            shutil.rmtree(path)


def plan_rollback(
    paths: UserPaths,
    transaction_id: str,
    *,
    expected_adapter: AdapterId | str | None = None,
) -> ChangePlan:
    if not transaction_id or any(
        character not in "0123456789abcdef" for character in transaction_id
    ):
        raise ProjectRulesError(
            "TRANSACTION_ID_INVALID",
            f"transaction ID is invalid: {transaction_id}",
        )
    manifest_path = paths.transactions_home / transaction_id / "manifest.json"
    if not manifest_path.is_file():
        raise ProjectRulesError(
            "TRANSACTION_MISSING",
            f"transaction does not exist: {transaction_id}",
        )
    raw = as_mapping(
        cast(object, json.loads(manifest_path.read_text(encoding="utf-8"))),
        name="transaction manifest",
    )
    _validate_transaction_adapter(raw, expected_adapter=expected_adapter)
    authorized_root = Path(as_string(raw["authorized_root"], name="authorized_root")).resolve()
    originals = as_object_tuple(raw.get("originals", ()), name="transaction originals")
    changes: list[Change] = []
    for original_value in originals:
        original = as_mapping(original_value, name="transaction original")
        logical = Path(as_string(original["target"], name="original target"))
        target = resolve_target_within_root(authorized_root / logical, authorized_root)
        kind = as_string(original["kind"], name="original kind")
        action = "remove" if kind == "missing" else f"restore-{kind}"
        changes.append(Change(action=action, target=target))
    return ChangePlan(scope="rollback", changes=tuple(changes))
