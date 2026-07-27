from __future__ import annotations

from pathlib import Path

import pytest

from project_execution_rules.catalog import load_builtin_catalog
from project_execution_rules.detection import detect_project
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.frontmatter import parse_frontmatter
from project_execution_rules.initialize import (
    ProjectSelection,
    initialize_project,
    plan_project_init,
)
from project_execution_rules.install import install_user_resources, plan_user_install
from project_execution_rules.models import ChangePlan
from project_execution_rules.paths import UserPaths
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

    targets = {change.target.name for change in plan.changes}
    assert "python-rules.md" in targets
    assert "security-rules.md" in targets
    assert "python-rules.override.md" in targets
    assert "testing-rules.override.md" not in targets
    assert "ruleset.yaml" in targets
    assert "AGENTS.md" in targets


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
