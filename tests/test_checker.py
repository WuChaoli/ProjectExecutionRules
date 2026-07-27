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
from project_execution_rules.rendering import render_agents
from project_execution_rules.status import get_project_status


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
        symlink_probe=lambda: True,
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
        ruleset.read_text(encoding="utf-8").replace("schema_version: 2", "schema_version: 9"),
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


def test_status_preserves_incompatible_state_for_invalid_yaml(tmp_path: Path) -> None:
    root = tmp_path / "project"
    rules = root / ".rules"
    rules.mkdir(parents=True)
    (rules / "ruleset.yaml").write_text("[invalid", encoding="utf-8")
    paths = UserPaths.from_environment({}, tmp_path / "home")

    status = get_project_status(root, paths)

    assert status.state is ProjectState.INCOMPATIBLE
    assert status.profile is None


def test_check_reports_invalid_override_frontmatter(tmp_path: Path) -> None:
    root, paths, tracked = _healthy_project(tmp_path)
    (root / ".rules" / "python-rules.override.md").write_text(
        "---\npaths:\n  - '**/*.py'\n# missing terminator\n",
        encoding="utf-8",
    )

    report = check_project(
        root,
        paths,
        tracked_files=tracked,
        link_verifier=_fake_link_verifier,
    )

    assert report.state is ProjectState.DRIFTED
    assert "OVERRIDE_FRONTMATTER_INVALID" in {issue.code for issue in report.issues}


def test_check_reports_invalid_override_operation(tmp_path: Path) -> None:
    root, paths, tracked = _healthy_project(tmp_path)
    override = root / ".rules" / "python-rules.override.md"
    override.write_text(
        """---
override_schema: 1
operations:
  - id: PY-OVR-001
    operation: replace
    target: PY-001
---

# Python Rule Overrides

- `PY-OVR-001`：替换 Base。
""",
        encoding="utf-8",
    )

    report = check_project(
        root,
        paths,
        tracked_files=tracked,
        link_verifier=_fake_link_verifier,
    )

    assert "OVERRIDE_OPERATION_INVALID" in {issue.code for issue in report.issues}


def test_check_reports_loaded_rules_budget_overflow(tmp_path: Path) -> None:
    root, paths, tracked = _healthy_project(tmp_path)
    for base in (root / ".rules").glob("*-rules.md"):
        base.write_text("x" * 9000, encoding="utf-8")

    report = check_project(
        root,
        paths,
        tracked_files=tracked,
        link_verifier=lambda link, target: True,
    )

    assert "LOADED_RULES_BUDGET_EXCEEDED" in {issue.code for issue in report.issues}


def test_check_reports_drifted_managed_user_rule(tmp_path: Path) -> None:
    root, paths, tracked = _healthy_project(tmp_path)
    (paths.rules_home / "security-rules.md").write_text("tampered\n", encoding="utf-8")

    report = check_project(
        root,
        paths,
        tracked_files=tracked,
        link_verifier=_fake_link_verifier,
    )

    assert report.state is ProjectState.DRIFTED
    assert "MANAGED_RESOURCE_DRIFTED" in {issue.code for issue in report.issues}


def test_check_reports_missing_task_route(tmp_path: Path) -> None:
    root, paths, tracked = _healthy_project(tmp_path)
    agents = root / "AGENTS.md"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace(
            "| Git 任务：branch、commit、merge、worktree | `.rules/git-rules.md` |",
            "",
        ),
        encoding="utf-8",
    )

    report = check_project(
        root,
        paths,
        tracked_files=tracked,
        link_verifier=_fake_link_verifier,
    )

    assert "AGENTS_ROUTE_MISSING" in {issue.code for issue in report.issues}


def test_agents_routes_explicit_commands_to_real_codex_entries() -> None:
    agents = render_agents(ProjectSelection(core_domains=("security", "agent", "tool", "harness")))

    assert "`agent-governance` -> Codex Skill `$agent-governance`" in agents
    assert (
        "`rules-review` -> 首选 CLI `project-rules review`；Codex Agent/Skill "
        "`rules-reviewer` 是同一 Schema 的交互适配器"
    ) in agents
