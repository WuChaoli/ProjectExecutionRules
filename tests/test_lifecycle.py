from __future__ import annotations

from pathlib import Path

import pytest

from project_execution_rules.catalog import load_builtin_catalog
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.lifecycle import (
    plan_project_update,
    plan_repair,
    plan_uninstall,
    plan_update,
    plan_user_uninstall,
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


def test_uninstall_refuses_regular_file_in_managed_link_slot(tmp_path: Path) -> None:
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
  profile: []
overrides: []
""",
        encoding="utf-8",
    )
    (rules / "security-rules.md").write_text("user content\n", encoding="utf-8")

    with pytest.raises(ProjectRulesError, match="non-managed"):
        plan_uninstall(root, _paths(tmp_path), include_user=False)


def test_project_update_changes_only_declared_rules_version(tmp_path: Path) -> None:
    root = tmp_path / "project"
    rules = root / ".rules"
    rules.mkdir(parents=True)
    ruleset = rules / "ruleset.yaml"
    ruleset.write_text(
        """schema_version: 1
rules_version: 0.9.0
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

    plan = plan_project_update(root, load_builtin_catalog())

    assert len(plan.changes) == 1
    content = plan.changes[0].content.decode()
    assert "rules_version: 1.0.0" in content
    assert "overrides:\n- python" in content


def test_user_uninstall_is_a_separate_scope(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    manifest = paths.state_home / "managed-user.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        '{"resource_version":"1.0.0","entries":[]}\n',
        encoding="utf-8",
    )

    plan = plan_user_uninstall(paths)

    assert plan.scope == "user"
    assert {change.target for change in plan.changes} == {manifest}


def test_rollback_rejects_unknown_transaction(tmp_path: Path) -> None:
    with pytest.raises(ProjectRulesError, match="transaction does not exist"):
        rollback_transaction(_paths(tmp_path), "deadbeef")
