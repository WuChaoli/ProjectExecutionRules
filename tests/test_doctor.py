from __future__ import annotations

from pathlib import Path

from project_execution_rules.doctor import CommandResult, run_doctor
from project_execution_rules.paths import UserPaths


def test_doctor_only_runs_non_destructive_tool_probes(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    paths = UserPaths.from_environment(
        {"LOCALAPPDATA": str(tmp_path / "local")},
        tmp_path / "home",
    )
    calls: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...]) -> CommandResult:
        calls.append(command)
        return CommandResult(returncode=0, stdout="ok", stderr="")

    report = run_doctor(
        root,
        paths,
        runner,
        symlink_probe=lambda: True,
    )

    assert report.ok
    assert "CODEX_CONFIG_MISSING" in {issue.code for issue in report.issues}
    assert calls == [("git", "--version"), ("codex", "--version")]
    assert all("pytest" not in command for call in calls for command in call)


def test_doctor_reports_missing_codex_and_symlink_capability(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    paths = UserPaths.from_environment({}, tmp_path / "home")

    def runner(command: tuple[str, ...]) -> CommandResult:
        return CommandResult(
            returncode=1 if command[0] == "codex" else 0,
            stdout="",
            stderr="missing",
        )

    report = run_doctor(root, paths, runner, symlink_probe=lambda: False)

    codes = {issue.code for issue in report.issues}
    assert {"GIT_REPOSITORY_MISSING", "CODEX_UNAVAILABLE", "SYMLINK_UNAVAILABLE"} <= codes
