from __future__ import annotations

import os
from pathlib import Path

from project_execution_rules.adapters import get_adapter
from project_execution_rules.managed import sha256_bytes
from project_execution_rules.models import AdapterId, ChangePlan, OperationReport, RuleCatalog
from project_execution_rules.paths import UserPaths
from project_execution_rules.selection import resolve_catalog_selection
from project_execution_rules.transactions import FileTransaction


def _plan_user_resources(
    paths: UserPaths,
    catalog: RuleCatalog,
    *,
    allow_managed_drift: bool,
) -> ChangePlan:
    selected = resolve_catalog_selection(
        catalog,
        catalog.rules,
        adapter=AdapterId.CODEX,
    )
    plan = get_adapter(AdapterId.CODEX).plan_install(
        paths,
        catalog,
        selected,
        allow_managed_drift=allow_managed_drift,
    )
    return ChangePlan(scope="user", changes=plan.changes)


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
    transaction = FileTransaction(
        paths.state_home,
        common_root,
        adapter=AdapterId.CODEX,
    )
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
