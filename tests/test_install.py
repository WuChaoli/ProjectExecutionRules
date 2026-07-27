from __future__ import annotations

from pathlib import Path

import pytest

from project_execution_rules.catalog import load_builtin_catalog
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.install import install_user_resources, plan_user_install
from project_execution_rules.paths import UserPaths


def _paths(tmp_path: Path) -> UserPaths:
    return UserPaths.from_environment(
        {"LOCALAPPDATA": str(tmp_path / "local")},
        tmp_path / "home",
    )


def test_user_install_plan_contains_rules_agent_and_skill(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    plan = plan_user_install(paths, load_builtin_catalog())

    targets = {change.target for change in plan.changes}
    assert paths.rules_home / "security-rules.md" in targets
    assert paths.codex_agents / "rules-reviewer.toml" in targets
    assert paths.codex_skills / "rules-reviewer" / "SKILL.md" in targets
    assert not any(target.exists() for target in targets)


def test_install_creates_canonical_resources_and_manifest(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    plan = plan_user_install(paths, load_builtin_catalog())

    report = install_user_resources(plan, paths, confirmed=True)

    assert report.changed
    assert (paths.rules_home / "python-rules.md").is_file()
    assert (paths.state_home / "managed-user.json").is_file()


def test_install_refuses_non_managed_conflict(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    conflict = paths.rules_home / "security-rules.md"
    conflict.parent.mkdir(parents=True)
    conflict.write_text("user content", encoding="utf-8")

    with pytest.raises(ProjectRulesError, match="non-managed"):
        plan_user_install(paths, load_builtin_catalog())
