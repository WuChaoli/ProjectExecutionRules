from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from project_execution_rules.adapters import get_adapter
from project_execution_rules.catalog import load_builtin_catalog, resource_root
from project_execution_rules.detection import detect_project
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.frontmatter import parse_frontmatter
from project_execution_rules.initialize import ProjectSelection
from project_execution_rules.managed import ManagedManifest
from project_execution_rules.models import AdapterId, ChangePlan
from project_execution_rules.paths import UserPaths
from project_execution_rules.selection import resolve_catalog_selection


def _paths(tmp_path: Path) -> UserPaths:
    return UserPaths.from_environment(
        {"LOCALAPPDATA": str(tmp_path / "local")},
        tmp_path / "home",
    )


def _install_claude(tmp_path: Path) -> UserPaths:
    paths = _paths(tmp_path)
    catalog = load_builtin_catalog()
    selection = resolve_catalog_selection(
        catalog,
        catalog.rules,
        adapter=AdapterId.CLAUDE,
    )
    plan = get_adapter(AdapterId.CLAUDE).plan_install(paths, catalog, selection)
    for change in plan.changes:
        change.target.parent.mkdir(parents=True, exist_ok=True)
        change.target.write_bytes(change.content)
    return paths


def _content(plan: ChangePlan, target: Path) -> str:
    return next(change.content.decode() for change in plan.changes if change.target == target)


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

    metadata, body = parse_frontmatter(_content(plan, paths.claude_agents / "rules-reviewer.md"))

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
    metadata, _ = parse_frontmatter(_content(plan, paths.claude_agents / "rules-reviewer.md"))

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
    assert all(change.action == "write" and change.link_target is None for change in first.changes)


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
        change for change in plan.changes if change.target == paths.manifest_path(AdapterId.CLAUDE)
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
        assert paths.claude_home.joinpath(entry.logical_path).is_relative_to(paths.claude_home)


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


def test_claude_project_init_creates_guide_and_only_non_empty_extensions(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    paths = _paths(tmp_path)
    catalog = load_builtin_catalog()
    selection = resolve_catalog_selection(
        catalog,
        catalog.rules,
        adapter=AdapterId.CLAUDE,
    )
    install_plan = get_adapter(AdapterId.CLAUDE).plan_install(paths, catalog, selection)
    for change in install_plan.changes:
        change.target.parent.mkdir(parents=True, exist_ok=True)
        change.target.write_bytes(change.content)

    plan = get_adapter(AdapterId.CLAUDE).plan_project_init(
        root,
        detect_project(root),
        ProjectSelection(
            core_domains=("security", "testing"),
            override_domains=("python",),
        ),
        paths,
    )

    targets = {change.target for change in plan.changes}
    assert root / ".claude" / "CLAUDE.md" in targets
    assert root / ".claude" / "rules" / "python.project.md" in targets
    assert root / ".claude" / "rules" / "testing.project.md" not in targets
    assert all(change.action == "write" for change in plan.changes)
    assert not any("skills" in change.target.parts for change in plan.changes)
    assert not any("agents" in change.target.parts for change in plan.changes)
    assert not any(change.link_target is not None for change in plan.changes)
    guide = _content(plan, root / ".claude" / "CLAUDE.md")
    assert "Project Rule Extensions" in guide
    assert ".rules/ruleset.yaml" in guide


def test_claude_project_init_preserves_existing_guide(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    guide = root / ".claude" / "CLAUDE.md"
    guide.parent.mkdir(parents=True)
    guide.write_text("project-owned\n", encoding="utf-8")
    paths = _paths(tmp_path)

    plan = get_adapter(AdapterId.CLAUDE).plan_project_init(
        root,
        detect_project(root),
        ProjectSelection(core_domains=("security",)),
        paths,
        verify_user_install=False,
    )

    assert guide not in {change.target for change in plan.changes}
    assert guide.read_text(encoding="utf-8") == "project-owned\n"


def test_claude_project_init_preserves_symlinked_guide(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    paths = _install_claude(tmp_path)
    guide = root / ".claude" / "CLAUDE.md"
    guide.parent.mkdir(parents=True)
    target = root / "project-guide.md"
    target.write_text("project-owned\n", encoding="utf-8")
    try:
        guide.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symbolic links are unavailable: {error}")

    plan = get_adapter(AdapterId.CLAUDE).plan_project_init(
        root,
        detect_project(root),
        ProjectSelection(core_domains=("security",)),
        paths,
    )

    assert guide not in {change.target for change in plan.changes}
    assert guide.is_symlink()
    assert target.read_text(encoding="utf-8") == "project-owned\n"


def test_claude_project_init_rejects_symlinked_claude_home(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    paths = _install_claude(tmp_path)
    outside = root / "outside-claude"
    outside.mkdir()
    try:
        (root / ".claude").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symbolic links are unavailable: {error}")

    with pytest.raises(ProjectRulesError) as caught:
        get_adapter(AdapterId.CLAUDE).plan_project_init(
            root,
            detect_project(root),
            ProjectSelection(core_domains=("security",)),
            paths,
        )

    assert caught.value.code == "PROJECT_OWNERSHIP_CONFLICT"


def test_claude_project_init_preserves_edited_extension(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname="sample"\nrequires-python=">=3.11"\n',
        encoding="utf-8",
    )
    paths = _install_claude(tmp_path)
    extension = root / ".claude" / "rules" / "python.project.md"
    extension.parent.mkdir(parents=True)
    extension.write_text("project-owned edit\n", encoding="utf-8")

    plan = get_adapter(AdapterId.CLAUDE).plan_project_init(
        root,
        detect_project(root),
        ProjectSelection(core_domains=("security",), override_domains=("python",)),
        paths,
    )

    assert extension not in {change.target for change in plan.changes}
    assert extension.read_text(encoding="utf-8") == "project-owned edit\n"


@pytest.mark.parametrize("unsafe_kind", ("directory", "symlink"))
def test_claude_project_init_rejects_unsafe_extension_target(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname="sample"\nrequires-python=">=3.11"\n',
        encoding="utf-8",
    )
    paths = _install_claude(tmp_path)
    extension = root / ".claude" / "rules" / "python.project.md"
    extension.parent.mkdir(parents=True)
    if unsafe_kind == "directory":
        extension.mkdir()
    else:
        target = root / "outside.md"
        target.write_text("outside\n", encoding="utf-8")
        try:
            extension.symlink_to(target)
        except OSError as error:
            pytest.skip(f"symbolic links are unavailable: {error}")

    with pytest.raises(ProjectRulesError) as caught:
        get_adapter(AdapterId.CLAUDE).plan_project_init(
            root,
            detect_project(root),
            ProjectSelection(core_domains=("security",), override_domains=("python",)),
            paths,
        )

    assert caught.value.code == "PROJECT_OWNERSHIP_CONFLICT"


def test_claude_project_init_rejects_symlinked_rules_ancestor(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname="sample"\nrequires-python=">=3.11"\n',
        encoding="utf-8",
    )
    paths = _install_claude(tmp_path)
    claude_home = root / ".claude"
    claude_home.mkdir()
    outside = root / "outside-rules"
    outside.mkdir()
    try:
        (claude_home / "rules").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symbolic links are unavailable: {error}")

    with pytest.raises(ProjectRulesError) as caught:
        get_adapter(AdapterId.CLAUDE).plan_project_init(
            root,
            detect_project(root),
            ProjectSelection(core_domains=("security",), override_domains=("python",)),
            paths,
        )

    assert caught.value.code == "PROJECT_OWNERSHIP_CONFLICT"


def test_claude_project_init_rejects_junctioned_rules_ancestor(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows junction test")
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname="sample"\nrequires-python=">=3.11"\n',
        encoding="utf-8",
    )
    paths = _install_claude(tmp_path)
    claude_home = root / ".claude"
    claude_home.mkdir()
    outside = root / "outside-rules"
    outside.mkdir()
    junction = claude_home / "rules"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("directory junction creation is unavailable")

    with pytest.raises(ProjectRulesError) as caught:
        get_adapter(AdapterId.CLAUDE).plan_project_init(
            root,
            detect_project(root),
            ProjectSelection(core_domains=("security",), override_domains=("python",)),
            paths,
        )

    assert caught.value.code == "PROJECT_OWNERSHIP_CONFLICT"


def test_claude_project_init_requires_matching_manifest_closure(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    paths = _paths(tmp_path)

    with pytest.raises(ProjectRulesError) as caught:
        get_adapter(AdapterId.CLAUDE).plan_project_init(
            root,
            detect_project(root),
            ProjectSelection(core_domains=("security",)),
            paths,
        )

    assert caught.value.code == "USER_ADAPTER_NOT_INSTALLED"


def test_claude_project_init_rejects_manifest_missing_selected_entry(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    paths = _paths(tmp_path)
    catalog = load_builtin_catalog()
    selection = resolve_catalog_selection(
        catalog,
        catalog.rules,
        adapter=AdapterId.CLAUDE,
    )
    install_plan = get_adapter(AdapterId.CLAUDE).plan_install(paths, catalog, selection)
    for change in install_plan.changes:
        change.target.parent.mkdir(parents=True, exist_ok=True)
        change.target.write_bytes(change.content)
    manifest_path = paths.manifest_path(AdapterId.CLAUDE)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entries"] = [
        entry for entry in manifest["entries"] if entry["logical_path"] != "rules/security.md"
    ]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ProjectRulesError) as caught:
        get_adapter(AdapterId.CLAUDE).plan_project_init(
            root,
            detect_project(root),
            ProjectSelection(core_domains=("security",)),
            paths,
        )

    assert caught.value.code == "USER_ADAPTER_CLOSURE_MISMATCH"


@pytest.mark.parametrize("corruption", ("extra-selection", "wrong-kind", "extra-entry"))
def test_claude_project_init_rejects_non_exact_global_closure(
    tmp_path: Path,
    corruption: str,
) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    paths = _install_claude(tmp_path)
    manifest_path = paths.manifest_path(AdapterId.CLAUDE)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if corruption == "extra-selection":
        manifest["selection"]["rules"].append("unknown-rule")
    elif corruption == "wrong-kind":
        entry = next(
            item for item in manifest["entries"] if item["logical_path"] == "rules/security.md"
        )
        entry["kind"] = "skill"
    else:
        manifest["entries"].append(
            {
                "logical_path": "rules/extra.md",
                "kind": "rule",
                "sha256": "0" * 64,
            }
        )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ProjectRulesError) as caught:
        get_adapter(AdapterId.CLAUDE).plan_project_init(
            root,
            detect_project(root),
            ProjectSelection(core_domains=("security",)),
            paths,
        )

    assert caught.value.code == "USER_ADAPTER_CLOSURE_MISMATCH"


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
