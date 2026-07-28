from __future__ import annotations

from pathlib import Path

import pytest

from project_execution_rules.adapters import get_adapter
from project_execution_rules.catalog import load_builtin_catalog
from project_execution_rules.checker import check_project
from project_execution_rules.detection import detect_project
from project_execution_rules.initialize import (
    ProjectSelection,
    initialize_project,
    plan_project_init,
)
from project_execution_rules.install import install_user_resources, plan_user_install
from project_execution_rules.models import (
    AdapterId,
    ChangePlan,
    CheckIssue,
    CheckReport,
    ProjectState,
)
from project_execution_rules.paths import UserPaths
from project_execution_rules.rendering import render_agents, render_ruleset
from project_execution_rules.selection import resolve_catalog_selection
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
        ProjectSelection(core_domains=("security", "git"), override_domains=("python",)),
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


def _apply(plan: ChangePlan) -> None:
    for change in plan.changes:
        change.target.parent.mkdir(parents=True, exist_ok=True)
        change.target.write_bytes(change.content)


def _multi_adapter_project(tmp_path: Path) -> tuple[Path, UserPaths, set[str]]:
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
    for adapter in (AdapterId.CODEX, AdapterId.CLAUDE):
        selection = resolve_catalog_selection(catalog, catalog.rules, adapter=adapter)
        _apply(get_adapter(adapter).plan_install(paths, catalog, selection))

    project_selection = ProjectSelection(
        core_domains=("security", "pull-request"),
        override_domains=(),
        adapters=(AdapterId.CODEX, AdapterId.CLAUDE),
    )
    plan = plan_project_init(root, detect_project(root), project_selection, paths)
    for change in plan.changes:
        change.target.parent.mkdir(parents=True, exist_ok=True)
        if change.action == "symlink":
            assert change.link_target is not None
            change.target.write_text(str(change.link_target.resolve()), encoding="utf-8")
        else:
            change.target.write_bytes(change.content)
    tracked = {change.target.relative_to(root).as_posix() for change in plan.changes}
    return root, paths, tracked


def _adapter_issues(report: CheckReport, adapter: AdapterId) -> list[CheckIssue]:
    return [issue for issue in report.issues if issue.evidence.get("adapter") == adapter.value]


def test_check_reports_healthy_project(tmp_path: Path) -> None:
    root, paths, tracked = _healthy_project(tmp_path)
    report = check_project(root, paths, tracked_files=tracked, link_verifier=_fake_link_verifier)
    assert report.state is ProjectState.HEALTHY
    assert report.issues == ()


def test_check_reports_missing_base_link(tmp_path: Path) -> None:
    root, paths, tracked = _healthy_project(tmp_path)
    (root / ".rules" / "git-rules.md").unlink()
    report = check_project(root, paths, tracked_files=tracked, link_verifier=_fake_link_verifier)
    assert report.state is ProjectState.DRIFTED
    assert "BASE_LINK_INVALID" in {issue.code for issue in report.issues}


def test_check_reports_incompatible_schema(tmp_path: Path) -> None:
    root, paths, tracked = _healthy_project(tmp_path)
    ruleset = root / ".rules" / "ruleset.yaml"
    ruleset.write_text(
        ruleset.read_text(encoding="utf-8").replace("schema_version: 2", "schema_version: 9"),
        encoding="utf-8",
    )
    report = check_project(root, paths, tracked_files=tracked, link_verifier=_fake_link_verifier)
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
        "---\npaths:\n  - '**/*.py'\n# missing terminator\n", encoding="utf-8"
    )
    report = check_project(root, paths, tracked_files=tracked, link_verifier=_fake_link_verifier)
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
    report = check_project(root, paths, tracked_files=tracked, link_verifier=_fake_link_verifier)
    assert "OVERRIDE_OPERATION_INVALID" in {issue.code for issue in report.issues}


def test_check_reports_loaded_rules_budget_overflow(tmp_path: Path) -> None:
    root, paths, tracked = _healthy_project(tmp_path)
    for base in (root / ".rules").glob("*-rules.md"):
        base.write_text("x" * 9000, encoding="utf-8")
    report = check_project(
        root, paths, tracked_files=tracked, link_verifier=lambda link, target: True
    )
    assert "LOADED_RULES_BUDGET_EXCEEDED" in {issue.code for issue in report.issues}


def test_check_reports_drifted_managed_user_rule(tmp_path: Path) -> None:
    root, paths, tracked = _healthy_project(tmp_path)
    (paths.rules_home / "security-rules.md").write_text("tampered\n", encoding="utf-8")
    report = check_project(root, paths, tracked_files=tracked, link_verifier=_fake_link_verifier)
    assert report.state is ProjectState.DRIFTED
    assert "MANAGED_RESOURCE_DRIFTED" in {issue.code for issue in report.issues}


def test_check_reports_missing_task_route(tmp_path: Path) -> None:
    root, paths, tracked = _healthy_project(tmp_path)
    agents = root / "AGENTS.md"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace(
            "| Git 任务：branch、commit、merge、worktree | `.rules/git-rules.md` |", ""
        ),
        encoding="utf-8",
    )
    report = check_project(root, paths, tracked_files=tracked, link_verifier=_fake_link_verifier)
    assert "AGENTS_ROUTE_MISSING" in {issue.code for issue in report.issues}


def test_manifest_drift_is_isolated_by_adapter(tmp_path: Path) -> None:
    root, paths, tracked = _multi_adapter_project(tmp_path)
    (paths.claude_rules / "security.md").write_text("tampered\n", encoding="utf-8")
    report = check_project(root, paths, tracked_files=tracked, link_verifier=_fake_link_verifier)
    assert {issue.code for issue in _adapter_issues(report, AdapterId.CLAUDE)} == {
        "MANAGED_RESOURCE_DRIFTED"
    }
    assert _adapter_issues(report, AdapterId.CODEX) == []


def test_missing_global_dependencies_are_reported_per_adapter(tmp_path: Path) -> None:
    root, paths, tracked = _multi_adapter_project(tmp_path)
    paths.manifest_path(AdapterId.CLAUDE).unlink()
    report = check_project(root, paths, tracked_files=tracked, link_verifier=_fake_link_verifier)
    assert "MANAGED_MANIFEST_MISSING" in {
        issue.code for issue in _adapter_issues(report, AdapterId.CLAUDE)
    }
    assert _adapter_issues(report, AdapterId.CODEX) == []


def test_malformed_claude_frontmatter_does_not_mask_codex(tmp_path: Path) -> None:
    root, paths, tracked = _multi_adapter_project(tmp_path)
    (paths.claude_skills / "pull-request" / "SKILL.md").write_text(
        "---\nname: pull-request\n", encoding="utf-8"
    )
    report = check_project(root, paths, tracked_files=tracked, link_verifier=_fake_link_verifier)
    assert "CLAUDE_SKILL_FRONTMATTER_INVALID" in {
        issue.code for issue in _adapter_issues(report, AdapterId.CLAUDE)
    }
    assert _adapter_issues(report, AdapterId.CODEX) == []


def test_claude_agent_rejects_user_only_skill_preload(tmp_path: Path) -> None:
    root, paths, tracked = _multi_adapter_project(tmp_path)
    (paths.claude_agents / "rules-reviewer.md").write_text(
        (
            "---\nname: rules-reviewer\ndescription: reviewer\n"
            "skills:\n  - rules-reviewer\n---\nbody\n"
        ),
        encoding="utf-8",
    )
    report = check_project(root, paths, tracked_files=tracked, link_verifier=_fake_link_verifier)
    assert "CLAUDE_AGENT_SKILLS_INVALID" in {
        issue.code for issue in _adapter_issues(report, AdapterId.CLAUDE)
    }


def test_project_skill_shadowing_is_an_error(tmp_path: Path) -> None:
    root, paths, tracked = _multi_adapter_project(tmp_path)
    local_skill = root / ".claude" / "skills" / "pull-request" / "SKILL.md"
    local_skill.parent.mkdir(parents=True)
    local_skill.write_text(
        "---\nname: pull-request\ndescription: local\n---\nlocal\n", encoding="utf-8"
    )
    report = check_project(root, paths, tracked_files=tracked, link_verifier=_fake_link_verifier)
    issue = next(issue for issue in report.issues if issue.code == "CLAUDE_SKILL_SHADOWED")
    assert issue.severity == "error"
    assert issue.evidence["adapter"] == "claude"


def test_project_agent_replacement_is_a_warning(tmp_path: Path) -> None:
    root, paths, tracked = _multi_adapter_project(tmp_path)
    local_agent = root / ".claude" / "agents" / "rules-reviewer.md"
    local_agent.parent.mkdir(parents=True)
    local_agent.write_text(
        "---\nname: rules-reviewer\ndescription: local\nskills: []\n---\nlocal\n",
        encoding="utf-8",
    )
    report = check_project(root, paths, tracked_files=tracked, link_verifier=_fake_link_verifier)
    issue = next(issue for issue in report.issues if issue.code == "CLAUDE_AGENT_REPLACED")
    assert issue.severity == "warning"
    assert report.state is ProjectState.HEALTHY


def test_project_rule_extension_must_match_selected_claude_override(tmp_path: Path) -> None:
    root, paths, tracked = _multi_adapter_project(tmp_path)
    extension = root / ".claude" / "rules" / "security.project.md"
    extension.parent.mkdir(parents=True, exist_ok=True)
    extension.write_text("project detail\n", encoding="utf-8")
    report = check_project(root, paths, tracked_files=tracked, link_verifier=_fake_link_verifier)
    assert "CLAUDE_EXTENSION_OUT_OF_SCOPE" in {
        issue.code for issue in _adapter_issues(report, AdapterId.CLAUDE)
    }


def test_missing_selected_project_rule_extension_is_reported(tmp_path: Path) -> None:
    root, paths, tracked = _multi_adapter_project(tmp_path)
    selection = ProjectSelection(
        core_domains=("security", "pull-request"),
        override_domains=("security",),
        adapters=(AdapterId.CODEX, AdapterId.CLAUDE),
    )
    (root / ".rules" / "ruleset.yaml").write_text(
        render_ruleset(selection, adapters=selection.adapters), encoding="utf-8"
    )
    report = check_project(root, paths, tracked_files=tracked, link_verifier=_fake_link_verifier)
    assert "CLAUDE_EXTENSION_MISSING" in {
        issue.code for issue in _adapter_issues(report, AdapterId.CLAUDE)
    }


def test_project_rule_extension_cannot_expand_base_paths(tmp_path: Path) -> None:
    root, paths, tracked = _multi_adapter_project(tmp_path)
    selection = ProjectSelection(
        core_domains=("security", "testing", "pull-request"),
        override_domains=("testing",),
        adapters=(AdapterId.CODEX, AdapterId.CLAUDE),
    )
    (root / ".rules" / "ruleset.yaml").write_text(
        render_ruleset(selection, adapters=selection.adapters), encoding="utf-8"
    )
    extension = root / ".claude" / "rules" / "testing.project.md"
    extension.parent.mkdir(parents=True, exist_ok=True)
    extension.write_text("---\npaths:\n  - '**/*'\n---\nproject detail\n", encoding="utf-8")
    report = check_project(root, paths, tracked_files=tracked, link_verifier=_fake_link_verifier)
    assert "CLAUDE_EXTENSION_TRIGGER_EXPANDED" in {
        issue.code for issue in _adapter_issues(report, AdapterId.CLAUDE)
    }


def test_missing_empty_claude_project_directories_are_healthy(tmp_path: Path) -> None:
    root, paths, tracked = _multi_adapter_project(tmp_path)
    assert not (root / ".claude" / "skills").exists()
    assert not (root / ".claude" / "agents").exists()
    report = check_project(root, paths, tracked_files=tracked, link_verifier=_fake_link_verifier)
    assert report.state is ProjectState.HEALTHY
    assert report.issues == ()


def test_shared_catalog_checks_run_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, paths, tracked = _multi_adapter_project(tmp_path)
    calls = 0

    def count_shared_check(catalog: object) -> tuple[object, ...]:
        nonlocal calls
        calls += 1
        return ()

    monkeypatch.setattr(
        "project_execution_rules.checker.validate_catalog_resources", count_shared_check
    )
    check_project(root, paths, tracked_files=tracked, link_verifier=_fake_link_verifier)
    assert calls == 1


def test_status_exposes_adapters_and_per_adapter_issue_counts(tmp_path: Path) -> None:
    root, paths, _ = _multi_adapter_project(tmp_path)
    (paths.claude_rules / "security.md").write_text("tampered\n", encoding="utf-8")
    status = get_project_status(
        root,
        paths,
        check_runner=lambda check_root, check_paths: check_project(
            check_root,
            check_paths,
            tracked_files=(),
            link_verifier=_fake_link_verifier,
        ),
    )
    assert status.adapters == (AdapterId.CODEX, AdapterId.CLAUDE)
    assert status.adapter_issue_counts == {"codex": 0, "claude": 1}
    assert status.to_dict()["adapters"] == ["codex", "claude"]


def test_agents_routes_explicit_commands_to_real_codex_entries() -> None:
    agents = render_agents(ProjectSelection(core_domains=("security", "agent", "tool", "harness")))
    assert "`agent-governance` -> Codex Skill `$agent-governance`" in agents
    assert (
        "`rules-review` -> 首选 CLI `project-rules review`；Codex Agent/Skill "
        "`rules-reviewer` 是同一 Schema 的交互适配器"
    ) in agents
