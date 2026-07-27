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


def test_offline_rules_workflow_without_project_command_execution(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
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
            core_domains=tuple(domain for domain, rule in catalog.rules.items() if rule.core),
            override_domains=("python",),
        ),
        paths,
    )

    def fake_symlink(link_target: str, target: Path) -> None:
        target.write_text(link_target, encoding="utf-8")

    def fake_link_verifier(link: Path, target: Path) -> bool:
        return link.is_file() and link.read_text(encoding="utf-8") == str(target.resolve())

    initialize_project(
        plan,
        root,
        paths,
        confirmed=True,
        symlink_factory=fake_symlink,
        link_verifier=fake_link_verifier,
        stage_files=lambda files: None,
        symlink_probe=lambda: True,
    )
    tracked = {
        "AGENTS.md",
        ".gitignore",
        ".rules/ruleset.yaml",
        ".rules/python-rules.override.md",
    }

    report = check_project(
        root,
        paths,
        tracked_files=tracked,
        link_verifier=fake_link_verifier,
    )

    assert report.state is ProjectState.HEALTHY
    assert report.issues == ()
