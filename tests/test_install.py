from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from project_execution_rules.adapters import get_adapter
from project_execution_rules.catalog import load_builtin_catalog
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.install import (
    install_user_resources,
    plan_user_install,
    plan_user_repair,
)
from project_execution_rules.lifecycle import plan_user_uninstall
from project_execution_rules.managed import (
    ManagedEntry,
    ManagedManifest,
    ManagedSelection,
    sha256_bytes,
)
from project_execution_rules.models import AdapterId
from project_execution_rules.paths import UserPaths
from project_execution_rules.selection import resolve_catalog_selection
from project_execution_rules.yaml_utils import as_mapping, as_string, load_mapping


def _paths(tmp_path: Path) -> UserPaths:
    return UserPaths.from_environment(
        {"LOCALAPPDATA": str(tmp_path / "local")},
        tmp_path / "home",
    )


def test_claude_install_plan_never_manages_global_claude_md(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    catalog = load_builtin_catalog()
    selection = resolve_catalog_selection(
        catalog,
        catalog.rules,
        adapter=AdapterId.CLAUDE,
    )

    plan = get_adapter(AdapterId.CLAUDE).plan_install(paths, catalog, selection)

    assert paths.claude_home / "CLAUDE.md" not in {
        change.target for change in plan.changes
    }


    paths = _paths(tmp_path)

    plan = plan_user_install(paths, load_builtin_catalog())

    targets = {change.target for change in plan.changes}
    assert paths.rules_home / "security-rules.md" in targets
    assert paths.codex_agents / "rules-reviewer.toml" in targets
    assert paths.codex_skills / "rules-reviewer" / "SKILL.md" in targets
    assert paths.codex_skills / "agent-governance" / "SKILL.md" in targets
    assert paths.codex_skills / "tool-governance" / "SKILL.md" in targets
    assert paths.rules_home / "review-report.schema.json" in targets
    assert not any(target.exists() for target in targets)


def test_install_creates_canonical_resources_and_manifest(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    plan = plan_user_install(paths, load_builtin_catalog())

    report = install_user_resources(plan, paths, confirmed=True)

    assert report.changed
    assert (paths.rules_home / "python-rules.md").is_file()
    manifest_path = paths.manifest_path(AdapterId.CODEX)
    manifest = ManagedManifest.load(manifest_path, expected_adapter=AdapterId.CODEX)
    assert manifest.adapter is AdapterId.CODEX
    assert "security" in manifest.selection.rules
    assert ".agents/rules/security-rules.md" in {
        entry.logical_path for entry in manifest.entries
    }
    assert not (paths.state_home / "managed-user.json").exists()


def test_installed_catalog_references_installed_rule_files(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    catalog = load_builtin_catalog()
    install_user_resources(plan_user_install(paths, catalog), paths, confirmed=True)
    installed_catalog = load_mapping(
        (paths.rules_home / "catalog.yaml").read_text(encoding="utf-8"),
        name="Installed Catalog",
    )
    installed_rules = as_mapping(installed_catalog["rules"], name="Installed Catalog rules")

    for domain, raw_rule in installed_rules.items():
        rule = as_mapping(raw_rule, name=f"Installed Catalog rule {domain}")
        relative_file = as_string(rule["file"], name=f"Installed Catalog file {domain}")
        assert (paths.rules_home / relative_file).is_file()


def test_install_refuses_non_managed_conflict(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    conflict = paths.rules_home / "security-rules.md"
    conflict.parent.mkdir(parents=True)
    conflict.write_text("user content", encoding="utf-8")

    with pytest.raises(ProjectRulesError, match="non-managed"):
        plan_user_install(paths, load_builtin_catalog())


def test_repeated_install_has_empty_plan(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    catalog = load_builtin_catalog()
    install_user_resources(plan_user_install(paths, catalog), paths, confirmed=True)

    plan = plan_user_install(paths, catalog)

    assert plan.changes == ()


def _directory_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("directory symlink privilege is unavailable")
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip("directory junction creation is unavailable")


def test_install_refuses_matching_content_through_direct_symlink(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    catalog = load_builtin_catalog()
    planned = plan_user_install(paths, catalog)
    security_change = next(
        change for change in planned.changes if change.target.name == "security-rules.md"
    )
    outside = tmp_path / "outside-security.md"
    outside.write_bytes(security_change.content)
    security_change.target.parent.mkdir(parents=True)
    try:
        security_change.target.symlink_to(outside)
    except OSError:
        pytest.skip("file symlink creation is unavailable")

    with pytest.raises(ProjectRulesError, match="non-managed"):
        plan_user_install(paths, catalog)

    assert not paths.manifest_path(AdapterId.CODEX).exists()


def test_install_refuses_matching_content_through_ancestor_reparse(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    catalog = load_builtin_catalog()
    planned = plan_user_install(paths, catalog)
    security_change = next(
        change for change in planned.changes if change.target.name == "security-rules.md"
    )
    outside_rules = tmp_path / "outside-rules"
    outside_rules.mkdir()
    (outside_rules / "security-rules.md").write_bytes(security_change.content)
    paths.rules_home.parent.mkdir(parents=True)
    _directory_link(paths.rules_home, outside_rules)

    with pytest.raises(ProjectRulesError, match="non-managed"):
        plan_user_install(paths, catalog)

    assert not paths.manifest_path(AdapterId.CODEX).exists()


def test_user_uninstall_keeps_managed_file_beneath_ancestor_reparse(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    outside_home = tmp_path / "outside-home"
    outside_rules = outside_home / ".agents" / "rules"
    outside_rules.mkdir(parents=True)
    target = outside_rules / "security-rules.md"
    target.write_bytes(b"security\n")
    paths.home.mkdir(parents=True)
    _directory_link(paths.home / ".agents", outside_home / ".agents")
    ManagedManifest(
        schema_version=2,
        adapter=AdapterId.CODEX,
        resource_version="1.0.0",
        selection=ManagedSelection(("security",), (), ()),
        entries=(
            ManagedEntry(
                ".agents/rules/security-rules.md",
                "rule",
                sha256_bytes(target.read_bytes()),
            ),
        ),
    ).save(paths.manifest_path(AdapterId.CODEX))

    plan = plan_user_uninstall(paths)

    assert target not in {change.target for change in plan.changes}
    assert target.is_file()


def test_user_repair_replaces_only_manifest_managed_drift(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    catalog = load_builtin_catalog()
    install_user_resources(plan_user_install(paths, catalog), paths, confirmed=True)
    drifted = paths.rules_home / "security-rules.md"
    drifted.write_text("tampered\n", encoding="utf-8")

    plan = plan_user_repair(paths, catalog)

    assert drifted in {change.target for change in plan.changes}
