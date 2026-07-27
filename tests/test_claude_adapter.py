from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from project_execution_rules.adapters import get_adapter
from project_execution_rules.catalog import load_builtin_catalog, resource_root
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.frontmatter import parse_frontmatter
from project_execution_rules.managed import ManagedManifest
from project_execution_rules.models import AdapterId, ChangePlan
from project_execution_rules.paths import UserPaths
from project_execution_rules.selection import resolve_catalog_selection


def _paths(tmp_path: Path) -> UserPaths:
    return UserPaths.from_environment(
        {"LOCALAPPDATA": str(tmp_path / "local")},
        tmp_path / "home",
    )


def _content(plan: ChangePlan, target: Path) -> str:
    return next(
        change.content.decode()
        for change in plan.changes
        if change.target == target
    )


def test_claude_adapter_is_registered_as_real_adapter() -> None:
    adapter = get_adapter(AdapterId.CLAUDE)

    assert type(adapter).__name__ == "ClaudeAdapter"
    assert adapter.id is AdapterId.CLAUDE


def test_claude_install_plans_dependency_closure(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    catalog = load_builtin_catalog()
    selection = resolve_catalog_selection(
        catalog,
        ("pull-request",),
        adapter=AdapterId.CLAUDE,
    )

    plan = get_adapter(AdapterId.CLAUDE).plan_install(paths, catalog, selection)

    targets = {change.target for change in plan.changes}
    assert paths.claude_rules / "pull-request.md" in targets
    assert paths.claude_skills / "pull-request" / "SKILL.md" in targets
    assert paths.claude_agents / "rules-reviewer.md" in targets
    assert paths.claude_home / "CLAUDE.md" not in targets
    assert paths.manifest_path(AdapterId.CLAUDE) in targets


def test_claude_rule_rendering_uses_only_native_paths_frontmatter(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    catalog = load_builtin_catalog()
    selection = resolve_catalog_selection(
        catalog,
        ("testing", "pull-request", "harness"),
        adapter=AdapterId.CLAUDE,
    )
    plan = get_adapter(AdapterId.CLAUDE).plan_install(paths, catalog, selection)

    paths_metadata, paths_body = parse_frontmatter(
        _content(plan, paths.claude_rules / "testing.md")
    )
    task_metadata, task_body = parse_frontmatter(
        _content(plan, paths.claude_rules / "pull-request.md")
    )
    explicit_metadata, explicit_body = parse_frontmatter(
        _content(plan, paths.claude_rules / "harness.md")
    )

    assert paths_metadata == {"paths": ["tests/**/*", "test/**/*"]}
    assert task_metadata == {}
    assert explicit_metadata == {}
    for body in (paths_body, task_body, explicit_body):
        assert all(section in body for section in ("## WHEN", "## MUST", "## MUST NOT"))
    assert "pull-request" in task_body
    assert "rules-reviewer" in explicit_body


def test_claude_skill_rendering_marks_only_user_invocation(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    catalog = load_builtin_catalog()
    selection = resolve_catalog_selection(
        catalog,
        ("pull-request", "harness"),
        adapter=AdapterId.CLAUDE,
    )
    plan = get_adapter(AdapterId.CLAUDE).plan_install(paths, catalog, selection)

    model_metadata, _ = parse_frontmatter(
        _content(plan, paths.claude_skills / "pull-request" / "SKILL.md")
    )
    user_metadata, _ = parse_frontmatter(
        _content(plan, paths.claude_skills / "rules-reviewer" / "SKILL.md")
    )

    assert model_metadata["name"] == "pull-request"
    assert "description" in model_metadata
    assert "disable-model-invocation" not in model_metadata
    assert user_metadata["name"] == "rules-reviewer"
    assert user_metadata["disable-model-invocation"] is True


def test_claude_agent_rendering_preloads_only_model_invocable_skills(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    catalog = load_builtin_catalog()
    selection = resolve_catalog_selection(
        catalog,
        ("pull-request",),
        adapter=AdapterId.CLAUDE,
    )
    plan = get_adapter(AdapterId.CLAUDE).plan_install(paths, catalog, selection)

    metadata, body = parse_frontmatter(
        _content(plan, paths.claude_agents / "rules-reviewer.md")
    )

    assert metadata["name"] == "rules-reviewer"
    assert isinstance(metadata["description"], str)
    assert metadata["description"]
    assert metadata["skills"] == ["pull-request"]
    assert "Canonical contract" in body


def test_claude_agent_without_preloads_renders_empty_skills_list(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    catalog = load_builtin_catalog()
    catalog.agents["rules-reviewer"] = replace(
        catalog.agents["rules-reviewer"],
        skills=(),
    )
    selection = resolve_catalog_selection(
        catalog,
        ("pull-request",),
        adapter=AdapterId.CLAUDE,
    )

    plan = get_adapter(AdapterId.CLAUDE).plan_install(paths, catalog, selection)
    metadata, _ = parse_frontmatter(
        _content(plan, paths.claude_agents / "rules-reviewer.md")
    )

    assert metadata["skills"] == []


def test_claude_install_is_deterministic_and_uses_only_regular_writes(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    catalog = load_builtin_catalog()
    selection = resolve_catalog_selection(
        catalog,
        ("pull-request", "testing"),
        adapter=AdapterId.CLAUDE,
    )
    adapter = get_adapter(AdapterId.CLAUDE)

    first = adapter.plan_install(paths, catalog, selection)
    second = adapter.plan_install(paths, catalog, selection)

    assert first == second
    assert all(
        change.action == "write" and change.link_target is None
        for change in first.changes
    )


def test_claude_manifest_selection_and_entries_match_planned_closure(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    catalog = load_builtin_catalog()
    selection = resolve_catalog_selection(
        catalog,
        ("pull-request",),
        adapter=AdapterId.CLAUDE,
    )
    plan = get_adapter(AdapterId.CLAUDE).plan_install(paths, catalog, selection)
    manifest_change = next(
        change
        for change in plan.changes
        if change.target == paths.manifest_path(AdapterId.CLAUDE)
    )
    manifest_change.target.parent.mkdir(parents=True)
    manifest_change.target.write_bytes(manifest_change.content)

    manifest = ManagedManifest.load(
        manifest_change.target,
        expected_adapter=AdapterId.CLAUDE,
    )

    assert manifest.selection.rules == selection.rules
    assert manifest.selection.skills == selection.skills
    assert manifest.selection.agents == selection.agents
    assert {entry.logical_path for entry in manifest.entries} == {
        "rules/pull-request.md",
        "skills/pull-request/SKILL.md",
        "agents/rules-reviewer.md",
    }
    for entry in manifest.entries:
        assert paths.claude_home.joinpath(entry.logical_path).is_relative_to(
            paths.claude_home
        )


@pytest.mark.parametrize(
    ("kind", "resource_id", "rule_ids", "error_code"),
    (
        ("rule", "pull-request", ("pull-request",), "RULE_RESOURCE_MISSING"),
        ("skill", "pull-request", ("pull-request",), "SKILL_RESOURCE_MISSING"),
        ("agent", "rules-reviewer", ("pull-request",), "AGENT_RESOURCE_MISSING"),
    ),
)
def test_claude_install_reports_stable_missing_resource_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    resource_id: str,
    rule_ids: tuple[str, ...],
    error_code: str,
) -> None:
    paths = _paths(tmp_path)
    catalog = load_builtin_catalog()
    selection = resolve_catalog_selection(
        catalog,
        rule_ids,
        adapter=AdapterId.CLAUDE,
    )
    original_root = Path(str(resource_root()))
    staged_root = tmp_path / "resources"

    shutil.copytree(original_root, staged_root)
    if kind == "rule":
        relative = Path("rules") / catalog.rules[resource_id].file
    elif kind == "skill":
        relative = Path(catalog.skills[resource_id].file)
    else:
        relative = Path(catalog.agents[resource_id].file)
    staged_root.joinpath(relative).unlink()
    monkeypatch.setattr(
        "project_execution_rules.adapters.claude.resource_root",
        lambda: staged_root,
    )

    with pytest.raises(ProjectRulesError) as caught:
        get_adapter(AdapterId.CLAUDE).plan_install(paths, catalog, selection)

    assert caught.value.code == error_code
    assert resource_id in caught.value.message
    assert str(staged_root.joinpath(relative)) in caught.value.evidence["path"]


def test_claude_install_refuses_non_managed_conflict(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    conflict = paths.claude_rules / "pull-request.md"
    conflict.parent.mkdir(parents=True)
    conflict.write_text("user content", encoding="utf-8")
    catalog = load_builtin_catalog()
    selection = resolve_catalog_selection(
        catalog,
        ("pull-request",),
        adapter=AdapterId.CLAUDE,
    )

    with pytest.raises(ProjectRulesError, match="non-managed"):
        get_adapter(AdapterId.CLAUDE).plan_install(paths, catalog, selection)
