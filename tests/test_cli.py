from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from project_execution_rules.cli import app

runner = CliRunner()


def test_help_lists_rules_lifecycle_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in (
        "install",
        "init",
        "status",
        "check",
        "review",
        "doctor",
        "update",
        "repair",
        "rollback",
        "uninstall",
    ):
        assert command in result.stdout


def test_no_argument_invocation_opens_interactive_menu() -> None:
    result = runner.invoke(app, input="exit\n")

    assert result.exit_code == 0
    assert "Project Execution Rules" in result.stdout
    assert "选择操作" in result.stdout


def test_status_json_for_unmanaged_project(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()

    result = runner.invoke(
        app,
        ["status", "--root", str(root), "--format", "json"],
        env={
            "USERPROFILE": str(tmp_path / "home"),
            "LOCALAPPDATA": str(tmp_path / "local"),
        },
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["state"] == "unmanaged"


def test_install_dry_run_json_does_not_write(tmp_path: Path) -> None:
    home = tmp_path / "home"

    result = runner.invoke(
        app,
        ["install", "--dry-run", "--format", "json"],
        env={
            "USERPROFILE": str(home),
            "LOCALAPPDATA": str(tmp_path / "local"),
        },
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["scope"] == "user"
    assert payload["changes"]
    assert not (home / ".agents" / "rules").exists()


def test_init_json_returns_stable_error_for_non_git_project(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["init", "--root", str(root), "--yes", "--format", "json"],
        env={
            "USERPROFILE": str(tmp_path / "home"),
            "LOCALAPPDATA": str(tmp_path / "local"),
        },
    )

    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["code"] == "GIT_REPOSITORY_MISSING"


def test_init_dry_run_reports_selected_triggers(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    environment = {
        "USERPROFILE": str(tmp_path / "home"),
        "LOCALAPPDATA": str(tmp_path / "local"),
    }
    installed = runner.invoke(
        app,
        ["install", "--yes", "--format", "json"],
        env=environment,
    )
    assert installed.exit_code == 0

    result = runner.invoke(
        app,
        [
            "init",
            "--root",
            str(root),
            "--core",
            "security,git",
            "--dry-run",
            "--format",
            "json",
        ],
        env=environment,
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    routes = {item["domain"]: item for item in payload["selection"]["rules"]}
    assert routes["security"]["activation"] == "always"
    assert routes["git"]["tasks"] == ["branch", "commit", "merge", "worktree"]
