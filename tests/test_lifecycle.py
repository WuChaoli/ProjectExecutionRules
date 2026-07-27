from __future__ import annotations

from pathlib import Path

import pytest

from project_execution_rules.catalog import load_builtin_catalog
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.lifecycle import (
    plan_repair,
    plan_uninstall,
    plan_update,
    rollback_transaction,
)
from project_execution_rules.paths import UserPaths


def _paths(tmp_path: Path) -> UserPaths:
    return UserPaths.from_environment(
        {"LOCALAPPDATA": str(tmp_path / "local")},
        tmp_path / "home",
    )


def test_update_plan_is_dry_run_and_contains_user_resources(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    plan = plan_update(paths, load_builtin_catalog())

    assert plan.scope == "user"
    assert plan.changes
    assert not paths.rules_home.exists()


def test_repair_plan_only_targets_managed_structure(tmp_path: Path) -> None:
    root = tmp_path / "project"
    rules = root / ".rules"
    rules.mkdir(parents=True)
    (rules / "ruleset.yaml").write_text(
        """schema_version: 1
rules_version: 1.0.0
adapter: codex
profile: python
domains:
  core:
    - security
  profile:
    - python
overrides:
  - python
""",
        encoding="utf-8",
    )
    (rules / "python-rules.override.md").write_text(
        "# Python Rule Overrides\n\n- `PY-OVR-001`：保留。\n",
        encoding="utf-8",
    )
    paths = _paths(tmp_path)
    paths.rules_home.mkdir(parents=True)
    for domain in ("security", "python"):
        (paths.rules_home / f"{domain}-rules.md").write_text("base", encoding="utf-8")

    plan = plan_repair(root, paths, link_verifier=lambda link, target: False)

    names = {change.target.name for change in plan.changes}
    assert {"security-rules.md", "python-rules.md"} <= names
    assert "python-rules.override.md" not in names


def test_uninstall_preserves_overrides(tmp_path: Path) -> None:
    root = tmp_path / "project"
    rules = root / ".rules"
    rules.mkdir(parents=True)
    (rules / "ruleset.yaml").write_text(
        """schema_version: 1
rules_version: 1.0.0
adapter: codex
profile: python
domains:
  core:
    - security
  profile:
    - python
overrides:
  - python
""",
        encoding="utf-8",
    )
    override = rules / "python-rules.override.md"
    override.write_text("# Override\n", encoding="utf-8")

    plan = plan_uninstall(root, _paths(tmp_path), include_user=False)

    assert override not in {change.target for change in plan.changes}
    assert rules / "ruleset.yaml" in {change.target for change in plan.changes}


def test_rollback_rejects_unknown_transaction(tmp_path: Path) -> None:
    with pytest.raises(ProjectRulesError, match="transaction does not exist"):
        rollback_transaction(_paths(tmp_path), "missing")
