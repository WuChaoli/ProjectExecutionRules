from __future__ import annotations

from pathlib import Path

import pytest

from project_execution_rules.adapters import get_adapter
from project_execution_rules.adapters.claude import ClaudeAdapter
from project_execution_rules.adapters.codex import CodexAdapter
from project_execution_rules.catalog import load_builtin_catalog
from project_execution_rules.detection import ProjectFacts, detect_project
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.frontmatter import parse_frontmatter
from project_execution_rules.initialize import (
    ProjectSelection,
    compose_project_changes,
    initialize_project,
    plan_project_init,
)
from project_execution_rules.install import install_user_resources, plan_user_install
from project_execution_rules.models import AdapterId, Change, ChangePlan
from project_execution_rules.paths import UserPaths
from project_execution_rules.rulesets import load_ruleset_text
from project_execution_rules.selection import resolve_catalog_selection
from project_execution_rules.yaml_utils import as_mapping, as_object_tuple


def _installed_paths(tmp_path: Path) -> UserPaths:
    paths = UserPaths.from_environment(
        {"LOCALAPPDATA": str(tmp_path / "local")},
        tmp_path / "home",
    )
    catalog = load_builtin_catalog()
    install_user_resources(
        plan_user_install(paths, catalog),
        paths,
        confirmed=True,
    )
    return paths


def _install_adapters(
    tmp_path: Path,
    adapters: tuple[AdapterId, ...],
) -> UserPaths:
    paths = UserPaths.from_environment(
        {"LOCALAPPDATA": str(tmp_path / "local")},
        tmp_path / "home",
    )
    catalog = load_builtin_catalog()
    for adapter in adapters:
        selection = resolve_catalog_selection(catalog, catalog.rules, adapter=adapter)
        plan = get_adapter(adapter).plan_install(paths, catalog, selection)
        for change in plan.changes:
            change.target.parent.mkdir(parents=True, exist_ok=True)
            change.target.write_bytes(change.content)
    return paths


def test_init_plan_has_exact_links_and_no_empty_overrides(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    paths = _installed_paths(tmp_path)
    selection = ProjectSelection(
        core_domains=("security", "testing", "git", "architecture"),
        override_domains=("python",),
    )

    plan = plan_project_init(root, detect_project(root), selection, paths)

    assert plan.scope == "project"
    targets = {change.target.name for change in plan.changes}
    assert "python-rules.md" in targets
    assert "security-rules.md" in targets
    assert "python-rules.override.md" in targets
    assert "testing-rules.override.md" not in targets
    assert "ruleset.yaml" in targets
    assert "AGENTS.md" in targets
    ruleset_change = next(
        change for change in plan.changes if change.target.name == "ruleset.yaml"
    )
    ruleset = load_ruleset_text(ruleset_change.content.decode())
    assert ruleset.adapters == (AdapterId.CODEX,)
    assert ruleset.overrides == {AdapterId.CODEX: ("python",)}


def test_python_override_declares_structured_operations(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    paths = _installed_paths(tmp_path)
    plan = plan_project_init(
        root,
        detect_project(root),
        ProjectSelection(
            core_domains=("security",),
            override_domains=("python",),
        ),
        paths,
    )
    override = next(
        change for change in plan.changes if change.target.name == "python-rules.override.md"
    )

    metadata, body = parse_frontmatter(override.content.decode())
    operations = [
        as_mapping(item, name="Override operation")
        for item in as_object_tuple(metadata["operations"], name="Override operations")
    ]

    assert metadata["override_schema"] == 1
    assert {operation["operation"] for operation in operations} == {"add_constraint"}
    assert {operation["target"] for operation in operations} == {"PY-001", "PY-003", "PY-006"}
    assert all(str(operation["id"]) in body for operation in operations)


def test_initialize_writes_contract_and_stages_governance_files(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    paths = _installed_paths(tmp_path)
    plan = plan_project_init(
        root,
        detect_project(root),
        ProjectSelection(
            core_domains=("security", "git"),
            override_domains=("python",),
        ),
        paths,
    )
    staged: list[tuple[Path, ...]] = []

    def fake_symlink(link_target: str, target: Path) -> None:
        target.write_text(link_target, encoding="utf-8")

    report = initialize_project(
        plan,
        root,
        paths,
        confirmed=True,
        symlink_factory=fake_symlink,
        link_verifier=lambda link, target: (
            link.read_text(encoding="utf-8") == str(target.resolve())
        ),
        stage_files=lambda files: staged.append(tuple(files)),
        symlink_probe=lambda: True,
    )

    assert report.changed
    assert (root / "AGENTS.md").is_file()
    assert (root / ".rules" / "ruleset.yaml").is_file()
    assert ".rules/python-rules.md" in (root / ".gitignore").read_text(encoding="utf-8")
    assert staged
    assert root / ".rules" / "python-rules.override.md" in staged[0]


def test_initialize_stops_before_writes_when_symlink_is_unavailable(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    paths = _installed_paths(tmp_path)
    plan = plan_project_init(
        root,
        detect_project(root),
        ProjectSelection(core_domains=("security",)),
        paths,
    )

    with pytest.raises(ProjectRulesError, match="symbolic link"):
        initialize_project(
            plan,
            root,
            paths,
            confirmed=True,
            symlink_probe=lambda: False,
            stage_files=lambda files: None,
        )

    assert not (root / ".rules").exists()
    assert not (root / "AGENTS.md").exists()


def test_init_plan_is_empty_when_project_already_matches_desired_state(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    paths = _installed_paths(tmp_path)
    selection = ProjectSelection(
        core_domains=("security", "git"),
        override_domains=("python",),
    )
    plan = plan_project_init(root, detect_project(root), selection, paths)
    for change in plan.changes:
        change.target.parent.mkdir(parents=True, exist_ok=True)
        if change.action == "write":
            change.target.write_bytes(change.content)
        elif change.link_target is not None:
            try:
                change.target.symlink_to(change.link_target)
            except OSError as error:
                pytest.skip(f"symbolic links are unavailable: {error}")

    repeated_plan = plan_project_init(root, detect_project(root), selection, paths)

    assert repeated_plan.changes == ()


def test_dry_run_planning_still_requires_git_repository(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    paths = UserPaths.from_environment({}, tmp_path / "home")

    with pytest.raises(ProjectRulesError, match="Git repository"):
        plan_project_init(
            root,
            detect_project(root),
            ProjectSelection(core_domains=("security",)),
            paths,
            verify_user_install=False,
        )


def test_dry_run_planning_still_requires_supported_profile(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    paths = UserPaths.from_environment({}, tmp_path / "home")

    with pytest.raises(ProjectRulesError, match="Python projects"):
        plan_project_init(
            root,
            detect_project(root),
            ProjectSelection(core_domains=("security",)),
            paths,
            verify_user_install=False,
        )


def test_init_composes_adapters_with_one_shared_ruleset(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    paths = _install_adapters(tmp_path, (AdapterId.CODEX, AdapterId.CLAUDE))

    plan = plan_project_init(
        root,
        detect_project(root),
        ProjectSelection(
            core_domains=("security",),
            override_domains=("python",),
            adapters=(AdapterId.CODEX, AdapterId.CLAUDE),
        ),
        paths,
    )

    ruleset_changes = [
        change for change in plan.changes if change.target == root / ".rules" / "ruleset.yaml"
    ]
    assert len(ruleset_changes) == 1
    ruleset = load_ruleset_text(ruleset_changes[0].content.decode())
    assert ruleset.adapters == (AdapterId.CODEX, AdapterId.CLAUDE)
    assert ruleset.overrides == {
        AdapterId.CODEX: ("python",),
        AdapterId.CLAUDE: ("python",),
    }
    targets = {change.target for change in plan.changes}
    assert root / "AGENTS.md" in targets
    assert root / ".claude" / "CLAUDE.md" in targets
    assert root / ".claude" / "rules" / "python.project.md" in targets


def _codex_collision_plan(
    self: CodexAdapter,
    root: Path,
    facts: ProjectFacts,
    selection: ProjectSelection,
    paths: UserPaths,
    *,
    verify_user_install: bool = True,
) -> ChangePlan:
    del self, facts, selection, paths, verify_user_install
    return ChangePlan(
        scope="project:codex",
        changes=(Change("write", root / "collision.md", b"codex"),),
    )


def _claude_collision_plan(
    self: ClaudeAdapter,
    root: Path,
    facts: ProjectFacts,
    selection: ProjectSelection,
    paths: UserPaths,
    *,
    verify_user_install: bool = True,
) -> ChangePlan:
    del self, facts, selection, paths, verify_user_install
    return ChangePlan(
        scope="project:claude",
        changes=(Change("write", root / "collision.md", b"claude"),),
    )


def test_init_rejects_cross_adapter_target_collisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    paths = _install_adapters(tmp_path, (AdapterId.CODEX, AdapterId.CLAUDE))
    codex = get_adapter(AdapterId.CODEX)
    claude = get_adapter(AdapterId.CLAUDE)
    monkeypatch.setattr(type(codex), "plan_project_init", _codex_collision_plan)
    monkeypatch.setattr(type(claude), "plan_project_init", _claude_collision_plan)

    with pytest.raises(ProjectRulesError) as caught:
        plan_project_init(
            root,
            detect_project(root),
            ProjectSelection(
                core_domains=("security",),
                adapters=(AdapterId.CODEX, AdapterId.CLAUDE),
            ),
            paths,
        )

    assert caught.value.code == "ADAPTER_PROJECT_COLLISION"


def test_project_composition_preserves_leaf_symlink_target(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    victim = root / "victim.md"
    victim.write_text("victim\n", encoding="utf-8")
    link = root / "planned.md"
    try:
        link.symlink_to(victim)
    except OSError as error:
        pytest.skip(f"symbolic links are unavailable: {error}")
    plan = ChangePlan(
        scope="project:claude",
        changes=(Change("write", link, b"replacement\n"),),
    )

    changes = compose_project_changes(root, ((AdapterId.CLAUDE, plan),))

    assert changes[0].target == link
    assert changes[0].target != victim
    staged: list[tuple[Path, ...]] = []
    report = initialize_project(
        ChangePlan(scope="project", changes=changes),
        root,
        UserPaths.from_environment({}, tmp_path / "home"),
        confirmed=True,
        stage_files=lambda files: staged.append(files),
    )

    assert report.changed
    assert not link.is_symlink()
    assert link.read_bytes() == b"replacement\n"
    assert victim.read_text(encoding="utf-8") == "victim\n"


def test_project_composition_rejects_reserved_ruleset_target(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    plan = ChangePlan(
        scope="project:codex",
        changes=(Change("write", root / ".rules" / "ruleset.yaml", b"adapter"),),
    )

    with pytest.raises(ProjectRulesError) as caught:
        compose_project_changes(root, ((AdapterId.CODEX, plan),))

    assert caught.value.code == "ADAPTER_PROJECT_CONTRACT"


def test_project_composition_rejects_reserved_ruleset_through_symlinked_parent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = root / "outside-rules"
    outside.mkdir()
    try:
        (root / ".rules").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symbolic links are unavailable: {error}")
    plan = ChangePlan(
        scope="project:codex",
        changes=(Change("write", root / ".rules" / "ruleset.yaml", b"adapter"),),
    )

    with pytest.raises(ProjectRulesError) as caught:
        compose_project_changes(root, ((AdapterId.CODEX, plan),))

    assert caught.value.code == "ADAPTER_PROJECT_CONTRACT"
    assert not (outside / "ruleset.yaml").exists()


def test_project_init_rejects_unsafe_ruleset_parent(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    outside = root / "outside-rules"
    outside.mkdir()
    try:
        (root / ".rules").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symbolic links are unavailable: {error}")
    paths = _install_adapters(tmp_path, (AdapterId.CLAUDE,))

    with pytest.raises(ProjectRulesError) as caught:
        plan_project_init(
            root,
            detect_project(root),
            ProjectSelection(
                core_domains=("security",),
                adapters=(AdapterId.CLAUDE,),
            ),
            paths,
        )

    assert caught.value.code == "ADAPTER_PROJECT_CONTRACT"
    assert not (outside / "ruleset.yaml").exists()


def test_project_composition_rejects_canonical_alias_collision(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    plans = (
        (
            AdapterId.CODEX,
            ChangePlan(
                scope="project:codex",
                changes=(Change("write", root / "same.md", b"codex"),),
            ),
        ),
        (
            AdapterId.CLAUDE,
            ChangePlan(
                scope="project:claude",
                changes=(Change("write", root / "x" / ".." / "same.md", b"claude"),),
            ),
        ),
    )

    with pytest.raises(ProjectRulesError) as caught:
        compose_project_changes(root, plans)

    assert caught.value.code == "ADAPTER_PROJECT_COLLISION"


def test_project_composition_rejects_target_outside_project(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    plan = ChangePlan(
        scope="project:claude",
        changes=(Change("write", tmp_path / "outside.md", b"outside"),),
    )

    with pytest.raises(ProjectRulesError) as caught:
        compose_project_changes(root, ((AdapterId.CLAUDE, plan),))

    assert caught.value.code == "ADAPTER_PROJECT_CONTRACT"


def test_init_through_symlinked_project_root_targets_real_project(tmp_path: Path) -> None:
    real_root = tmp_path / "real-project"
    (real_root / ".git").mkdir(parents=True)
    (real_root / "pyproject.toml").write_text(
        '[project]\nname="sample"\nrequires-python=">=3.11"\n',
        encoding="utf-8",
    )
    root_alias = tmp_path / "project-alias"
    try:
        root_alias.symlink_to(real_root, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks are unavailable: {error}")
    paths = _install_adapters(tmp_path, (AdapterId.CLAUDE,))

    plan = plan_project_init(
        root_alias,
        detect_project(root_alias),
        ProjectSelection(
            core_domains=("security",),
            override_domains=("python",),
            adapters=(AdapterId.CLAUDE,),
        ),
        paths,
    )

    assert plan.changes
    assert all(change.target.is_relative_to(real_root) for change in plan.changes)
    staged: list[tuple[Path, ...]] = []
    report = initialize_project(
        plan,
        root_alias,
        paths,
        confirmed=True,
        stage_files=lambda files: staged.append(files),
        symlink_probe=lambda: pytest.fail("Claude-only init must not probe symlinks"),
    )

    assert report.changed
    assert (real_root / ".claude" / "CLAUDE.md").is_file()
    assert (real_root / ".claude" / "rules" / "python.project.md").is_file()
    assert (real_root / ".rules" / "ruleset.yaml").is_file()
    assert all(path.is_relative_to(real_root) for path in staged[0])
    assert not (tmp_path / ".claude").exists()


def test_claude_only_init_does_not_probe_symlink_capability(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    paths = _install_adapters(tmp_path, (AdapterId.CLAUDE,))
    plan = plan_project_init(
        root,
        detect_project(root),
        ProjectSelection(
            core_domains=("security",),
            override_domains=("python",),
            adapters=(AdapterId.CLAUDE,),
        ),
        paths,
    )
    staged: list[tuple[Path, ...]] = []

    report = initialize_project(
        plan,
        root,
        paths,
        confirmed=True,
        symlink_probe=lambda: pytest.fail("Claude-only init must not probe symlinks"),
        stage_files=lambda files: staged.append(files),
    )

    assert report.changed
    assert staged == [
        (
            root / ".claude" / "CLAUDE.md",
            root / ".claude" / "rules" / "python.project.md",
            root / ".rules" / "ruleset.yaml",
        )
    ]
    assert not (root / ".claude" / "skills").exists()
    assert not (root / ".claude" / "agents").exists()


def test_init_does_not_implicitly_install_missing_adapter(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    paths = UserPaths.from_environment({}, tmp_path / "home")

    with pytest.raises(ProjectRulesError) as caught:
        plan_project_init(
            root,
            detect_project(root),
            ProjectSelection(
                core_domains=("security",),
                adapters=(AdapterId.CLAUDE,),
            ),
            paths,
        )

    assert caught.value.code == "USER_ADAPTER_NOT_INSTALLED"
    assert not paths.manifest_path(AdapterId.CLAUDE).exists()


def test_initialize_empty_plan_does_not_probe_or_stage(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    paths = UserPaths.from_environment({}, tmp_path / "home")

    report = initialize_project(
        ChangePlan(scope="project", changes=()),
        root,
        paths,
        confirmed=True,
        symlink_probe=lambda: pytest.fail("empty plan must not probe symlink capability"),
        stage_files=lambda files: pytest.fail("empty plan must not stage files"),
    )

    assert not report.changed
    assert report.transaction_id is None
