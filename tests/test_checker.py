from __future__ import annotations

from pathlib import Path

from project_execution_rules.catalog import load_builtin_catalog
from project_execution_rules.checker import check_project
from project_execution_rules.detection import detect_project
from project_execution_rules.initialize import (
    ProjectSelection,
    initialize_project,
    plan_project_init,
)
from project_execution_rules.install import install_user_resources, plan_user_install
from project_execution_rules.models import ProjectState
from project_execution_rules.paths import UserPaths


def _healthy_project(tmp_path: Path) -> tuple[Path, UserPaths, set[str]]:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    paths = UserPaths.from_environment(
        {"LOCALAPPDATA": str(tmp_path / "local")},
        tmp_path / "home",
    )
    catalog = load_builtin_catalog()
    install_user_resources(plan_user_install(paths, catalog), paths, confirmed=True)
    plan = plan_project_init(
        root,
        detect_project(root),
        ProjectSelection(
            core_domains=("security", "git"),
            override_domains=("python",),
        ),
        paths,
    )

    def fake_symlink(link_target: str, target: Path) -> None:
        target.write_text(link_target, encoding="utf-8")

    initialize_project(
        plan,
        root,
        paths,
        confirmed=True,
        symlink_factory=fake_symlink,
        link_verifier=lambda link, target: (
            link.read_text(encoding="utf-8") == str(target.resolve())
        ),
        stage_files=lambda files: None,
    )
    tracked = {
        "AGENTS.md",
        ".gitignore",
        ".rules/ruleset.yaml",
        ".rules/python-rules.override.md",
    }
    return root, paths, tracked


def _fake_link_verifier(link: Path, target: Path) -> bool:
    return link.is_file() and link.read_text(encoding="utf-8") == str(target.resolve())


def test_check_reports_healthy_project(tmp_path: Path) -> None:
    root, paths, tracked = _healthy_project(tmp_path)

    report = check_project(
        root,
        paths,
        tracked_files=tracked,
        link_verifier=_fake_link_verifier,
    )

    assert report.state is ProjectState.HEALTHY
    assert report.issues == ()


def test_check_reports_missing_base_link(tmp_path: Path) -> None:
    root, paths, tracked = _healthy_project(tmp_path)
    (root / ".rules" / "git-rules.md").unlink()

    report = check_project(
        root,
        paths,
        tracked_files=tracked,
        link_verifier=_fake_link_verifier,
    )

    assert report.state is ProjectState.DRIFTED
    assert "BASE_LINK_INVALID" in {issue.code for issue in report.issues}


def test_check_reports_incompatible_schema(tmp_path: Path) -> None:
    root, paths, tracked = _healthy_project(tmp_path)
    ruleset = root / ".rules" / "ruleset.yaml"
    ruleset.write_text(
        ruleset.read_text(encoding="utf-8").replace("schema_version: 1", "schema_version: 9"),
        encoding="utf-8",
    )

    report = check_project(
        root,
        paths,
        tracked_files=tracked,
        link_verifier=_fake_link_verifier,
    )

    assert report.state is ProjectState.INCOMPATIBLE
    assert "RULESET_SCHEMA_INCOMPATIBLE" in {issue.code for issue in report.issues}
