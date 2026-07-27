from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
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


def test_json_mutation_requires_yes_and_returns_one_error_object(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["install", "--format", "json"],
        env={
            "USERPROFILE": str(tmp_path / "home"),
            "LOCALAPPDATA": str(tmp_path / "local"),
        },
    )

    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["code"] == "CONFIRMATION_REQUIRED"


def test_corrupt_managed_manifest_returns_stable_json_error(tmp_path: Path) -> None:
    local = tmp_path / "local"
    manifest = local / "ProjectExecutionRules" / "managed-user-codex.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{broken", encoding="utf-8")

    result = runner.invoke(
        app,
        ["install", "--dry-run", "--format", "json"],
        env={
            "USERPROFILE": str(tmp_path / "home"),
            "LOCALAPPDATA": str(local),
        },
    )

    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["code"] == "MANAGED_MANIFEST_INVALID"


def test_update_stops_when_user_level_update_is_declined(tmp_path: Path) -> None:
    home = tmp_path / "home"
    local = tmp_path / "local"
    environment = {
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(local),
    }
    installed = runner.invoke(
        app,
        ["install", "--yes", "--format", "json"],
        env=environment,
    )
    assert installed.exit_code == 0
    security = home / ".agents" / "rules" / "security-rules.md"
    old_content = b"OLD SECURITY RULE\n"
    security.write_bytes(old_content)
    manifest = local / "ProjectExecutionRules" / "managed-user-codex.json"
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    for entry in manifest_payload["entries"]:
        if entry["logical_path"] == ".agents/rules/security-rules.md":
            entry["sha256"] = hashlib.sha256(old_content).hexdigest()
    manifest_payload["resource_version"] = "0.9.0"
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    root = tmp_path / "project"
    rules = root / ".rules"
    rules.mkdir(parents=True)
    ruleset = rules / "ruleset.yaml"
    ruleset.write_text(
        """schema_version: 2
rules_version: 0.9.0
adapters:
  - codex
profile: python
domains:
  core:
    - security
  profile:
    - python
overrides:
  codex: []
""",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["update", "--root", str(root)],
        input="n\n",
        env=environment,
    )

    assert result.exit_code != 0
    assert "rules_version: 0.9.0" in ruleset.read_text(encoding="utf-8")


def _snapshot_files(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_init_preserves_installed_user_resources(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    home = tmp_path / "home"
    local = tmp_path / "local"
    environment = {"USERPROFILE": str(home), "LOCALAPPDATA": str(local)}
    installed = runner.invoke(
        app,
        ["install", "--yes", "--format", "json"],
        env=environment,
    )
    assert installed.exit_code == 0
    before_home = _snapshot_files(home)
    before_state = _snapshot_files(local / "ProjectExecutionRules")

    result = runner.invoke(
        app,
        ["init", "--root", str(root), "--yes", "--format", "json"],
        env=environment,
    )

    assert result.exit_code == 0
    assert _snapshot_files(home) == before_home
    assert _snapshot_files(local / "ProjectExecutionRules") == before_state


def test_init_does_not_install_missing_user_resources(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    home = tmp_path / "home"
    local = tmp_path / "local"

    result = runner.invoke(
        app,
        ["init", "--root", str(root), "--yes", "--format", "json"],
        env={"USERPROFILE": str(home), "LOCALAPPDATA": str(local)},
    )

    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["code"] == "USER_ADAPTER_NOT_INSTALLED"
    assert "install" in payload["remediation"]
    assert not (home / ".agents").exists()
    assert not (home / ".codex").exists()
    assert not (local / "ProjectExecutionRules" / "managed-user-codex.json").exists()


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


def _write_cli_rollback_transaction(
    tmp_path: Path,
    *,
    adapter: object = None,
    include_adapter: bool,
) -> tuple[dict[str, str], Path]:
    home = tmp_path / "home"
    local = tmp_path / "local"
    target = home / "managed.md"
    target.parent.mkdir(parents=True)
    target.write_text("changed\n", encoding="utf-8")
    transaction = local / "ProjectExecutionRules" / "transactions" / "deadbeef"
    backup = local / "ProjectExecutionRules" / "backups" / "deadbeef" / "0.bin"
    transaction.mkdir(parents=True)
    backup.parent.mkdir(parents=True)
    backup.write_text("original\n", encoding="utf-8")
    payload: dict[str, object] = {
        "authorized_root": str(home),
        "originals": [
            {
                "target": "managed.md",
                "kind": "file",
                "backup": str(backup),
                "link_target": "",
            }
        ],
    }
    if include_adapter:
        payload["adapter"] = adapter
    (transaction / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    return {
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(local),
    }, target


@pytest.mark.parametrize(
    ("adapter", "include_adapter"),
    (("claude", True), (None, False)),
)
def test_cli_rollback_rejects_non_codex_transaction_before_modifying_target(
    tmp_path: Path,
    adapter: object,
    include_adapter: bool,
) -> None:
    environment, target = _write_cli_rollback_transaction(
        tmp_path,
        adapter=adapter,
        include_adapter=include_adapter,
    )

    result = runner.invoke(
        app,
        ["rollback", "deadbeef", "--yes", "--format", "json"],
        env=environment,
    )

    assert result.exit_code != 0
    assert json.loads(result.stdout)["code"].startswith("TRANSACTION_ADAPTER_")
    assert target.read_text(encoding="utf-8") == "changed\n"


def test_cli_rollback_preview_rejects_non_codex_transaction(tmp_path: Path) -> None:
    environment, target = _write_cli_rollback_transaction(
        tmp_path,
        adapter="claude",
        include_adapter=True,
    )

    result = runner.invoke(
        app,
        ["rollback", "deadbeef", "--dry-run", "--format", "json"],
        env=environment,
    )

    assert result.exit_code != 0
    assert json.loads(result.stdout)["code"] == "TRANSACTION_ADAPTER_MISMATCH"
    assert target.read_text(encoding="utf-8") == "changed\n"


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
    assert payload["project"]["scope"] == "project"
    assert routes["security"]["activation"] == "always"
    assert routes["git"]["tasks"] == ["branch", "commit", "merge", "worktree"]
