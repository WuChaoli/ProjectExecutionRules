from __future__ import annotations

from pathlib import Path

from project_execution_rules.catalog import load_builtin_catalog
from project_execution_rules.detection import detect_project
from project_execution_rules.initialize import (
    ProjectSelection,
    initialize_project,
    plan_project_init,
)
from project_execution_rules.install import install_user_resources, plan_user_install
from project_execution_rules.paths import UserPaths


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
    )

    assert report.changed
    assert (root / "AGENTS.md").is_file()
    assert (root / ".rules" / "ruleset.yaml").is_file()
    assert ".rules/python-rules.md" in (root / ".gitignore").read_text(encoding="utf-8")
    assert staged
    assert root / ".rules" / "python-rules.override.md" in staged[0]
