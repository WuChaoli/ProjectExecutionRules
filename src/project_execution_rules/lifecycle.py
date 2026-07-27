from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import cast

import yaml

from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.initialize import ProjectSelection
from project_execution_rules.install import plan_user_install
from project_execution_rules.managed import ManagedManifest, sha256_bytes
from project_execution_rules.models import Change, ChangePlan, OperationReport, RuleCatalog
from project_execution_rules.paths import UserPaths
from project_execution_rules.rendering import render_agents
from project_execution_rules.transactions import FileTransaction, resolve_target_within_root
from project_execution_rules.yaml_utils import (
    as_mapping,
    as_object_tuple,
    as_string,
    as_string_tuple,
    load_mapping,
)


def plan_update(paths: UserPaths, catalog: RuleCatalog) -> ChangePlan:
    return plan_user_install(paths, catalog)


def plan_project_update(root: Path, catalog: RuleCatalog) -> ChangePlan:
    raw = _load_ruleset(root.resolve())
    if raw.get("rules_version") == catalog.rules_version:
        return ChangePlan(scope="project", changes=())
    raw["rules_version"] = catalog.rules_version
    content = yaml.safe_dump(
        raw,
        allow_unicode=True,
        sort_keys=False,
    ).encode()
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


def _load_ruleset(root: Path) -> dict[str, object]:
    path = root / ".rules" / "ruleset.yaml"
    if not path.is_file():
        raise ProjectRulesError(
            "RULESET_MISSING",
            "project Rule Set does not exist",
        )
    try:
        return load_mapping(path.read_text(encoding="utf-8"), name="Rule Set")
    except ValueError as error:
        raise ProjectRulesError("RULESET_INVALID", str(error)) from error


def _actual_link_verifier(link: Path, target: Path) -> bool:
    return link.is_symlink() and link.resolve() == target.resolve()


def plan_repair(
    root: Path,
    paths: UserPaths,
    *,
    link_verifier: Callable[[Path, Path], bool] = _actual_link_verifier,
) -> ChangePlan:
    resolved = root.resolve()
    raw = _load_ruleset(resolved)
    try:
        domains_raw = as_mapping(raw.get("domains", {}), name="Rule Set domains")
        core = as_string_tuple(domains_raw.get("core", ()), name="Core domains")
        profile = as_string_tuple(domains_raw.get("profile", ()), name="Profile domains")
    except ValueError as error:
        raise ProjectRulesError("RULESET_INVALID", str(error)) from error
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
    raw = _load_ruleset(resolved)
    try:
        domains_raw = as_mapping(raw.get("domains", {}), name="Rule Set domains")
        core = as_string_tuple(domains_raw.get("core", ()), name="Core domains")
        profile = as_string_tuple(domains_raw.get("profile", ()), name="Profile domains")
        domains = core + profile
    except ValueError as error:
        raise ProjectRulesError("RULESET_INVALID", str(error)) from error
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
    desired_agents = render_agents(ProjectSelection(core_domains=core))
    if agents.is_file() and agents.read_text(encoding="utf-8") == desired_agents:
        changes.append(Change(action="remove", target=agents))
    if include_user:
        raise ProjectRulesError(
            "TRANSACTION_SCOPE_MIXED",
            "user and project uninstall must use separate transactions",
        )
    return ChangePlan(scope="project", changes=tuple(changes))


def plan_user_uninstall(paths: UserPaths) -> ChangePlan:
    manifest_path = paths.state_home / "managed-user.json"
    if not manifest_path.is_file():
        return ChangePlan(scope="user", changes=())
    manifest = ManagedManifest.load(manifest_path)
    changes: list[Change] = []
    for entry in manifest.entries:
        target = paths.home / Path(entry.logical_path)
        try:
            target.absolute().relative_to(paths.home.resolve())
            target.parent.resolve(strict=False).relative_to(paths.home.resolve())
        except ValueError as error:
            raise ProjectRulesError(
                "MANAGED_RESOURCE_PATH_INVALID",
                f"managed resource path escapes the user home: {entry.logical_path}",
            ) from error
        if (
            not target.is_symlink()
            and target.is_file()
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
    else:
        authorized_root = Path(os.path.commonpath([root, paths.home, paths.state_home]))
    transaction = FileTransaction(
        paths.state_home,
        authorized_root,
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


def rollback_transaction(paths: UserPaths, transaction_id: str) -> None:
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
    authorized_root = Path(as_string(raw["authorized_root"], name="authorized_root")).resolve()
    originals = as_object_tuple(raw.get("originals", ()), name="transaction originals")
    for original_value in reversed(originals):
        original = as_mapping(original_value, name="transaction original")
        try:
            target = resolve_target_within_root(
                Path(as_string(original["target"], name="original target")),
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
    backup_home = paths.backups_home / transaction_id
    for path in (transaction_home, backup_home):
        if path.exists():
            path.resolve().relative_to(paths.state_home.resolve())
            shutil.rmtree(path)
