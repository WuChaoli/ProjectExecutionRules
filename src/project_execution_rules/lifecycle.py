from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import yaml

from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.initialize import ProjectSelection
from project_execution_rules.install import plan_user_install
from project_execution_rules.managed import ManagedManifest, sha256_bytes
from project_execution_rules.models import Change, ChangePlan, OperationReport, RuleCatalog
from project_execution_rules.paths import UserPaths
from project_execution_rules.rendering import render_agents
from project_execution_rules.transactions import FileTransaction


def plan_update(paths: UserPaths, catalog: RuleCatalog) -> ChangePlan:
    return plan_user_install(paths, catalog)


def _load_ruleset(root: Path) -> dict[str, object]:
    path = root / ".rules" / "ruleset.yaml"
    if not path.is_file():
        raise ProjectRulesError(
            "RULESET_MISSING",
            "project Rule Set does not exist",
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ProjectRulesError("RULESET_INVALID", "project Rule Set is invalid")
    return raw


def plan_repair(
    root: Path,
    paths: UserPaths,
    *,
    link_verifier: Callable[[Path, Path], bool] = (
        lambda link, target: link.is_symlink() and link.resolve() == target.resolve()
    ),
) -> ChangePlan:
    resolved = root.resolve()
    raw = _load_ruleset(resolved)
    domains_raw = raw.get("domains", {})
    if not isinstance(domains_raw, dict):
        raise ProjectRulesError("RULESET_INVALID", "Rule Set domains are invalid")
    core = tuple(str(item) for item in domains_raw.get("core", ()))
    profile = tuple(str(item) for item in domains_raw.get("profile", ()))
    changes: list[Change] = []
    for domain in core + profile:
        link = resolved / ".rules" / f"{domain}-rules.md"
        target = paths.rules_home / f"{domain}-rules.md"
        if not target.is_file():
            raise ProjectRulesError(
                "USER_RULE_MISSING",
                f"cannot repair missing user Rule: {domain}",
            )
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
    domains_raw = raw.get("domains", {})
    if not isinstance(domains_raw, dict):
        domains_raw = {}
    domains = tuple(domains_raw.get("core", ())) + tuple(domains_raw.get("profile", ()))
    changes = [
        Change(
            action="remove",
            target=resolved / ".rules" / f"{domain}-rules.md",
        )
        for domain in domains
    ]
    changes.append(Change(action="remove", target=resolved / ".rules" / "ruleset.yaml"))
    agents = resolved / "AGENTS.md"
    if agents.is_file() and agents.read_text(encoding="utf-8").startswith("# Project Rules Router"):
        changes.append(Change(action="remove", target=agents))
    if include_user:
        manifest_path = paths.state_home / "managed-user.json"
        if manifest_path.is_file():
            manifest = ManagedManifest.load(manifest_path)
            for entry in manifest.entries:
                target = paths.home / Path(entry.logical_path)
                if target.is_file() and sha256_bytes(target.read_bytes()) == entry.sha256:
                    changes.append(Change(action="remove", target=target))
            changes.append(Change(action="remove", target=manifest_path))
    return ChangePlan(
        scope="combined" if include_user else "project",
        changes=tuple(changes),
    )


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
    verifier = link_verifier or (
        lambda link, target: link.is_symlink() and link.resolve() == target.resolve()
    )

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
    transaction_home = paths.transactions_home / transaction_id
    manifest_path = transaction_home / "manifest.json"
    if not manifest_path.is_file():
        raise ProjectRulesError(
            "TRANSACTION_MISSING",
            f"transaction does not exist: {transaction_id}",
        )
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    authorized_root = Path(raw["authorized_root"]).resolve()
    originals = raw.get("originals", ())
    for original in reversed(originals):
        target = Path(original["target"]).absolute()
        try:
            target.relative_to(authorized_root)
        except ValueError as error:
            raise ProjectRulesError(
                "TRANSACTION_TARGET_INVALID",
                f"transaction target is outside authorized root: {target}",
            ) from error
        if target.is_file() or target.is_symlink():
            target.unlink()
        elif target.exists():
            raise ProjectRulesError(
                "TRANSACTION_TARGET_UNSAFE",
                f"refusing to replace non-file target: {target}",
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        kind = original["kind"]
        if kind == "file":
            target.write_bytes(Path(original["backup"]).read_bytes())
        elif kind == "symlink":
            os.symlink(original["link_target"], target)
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
