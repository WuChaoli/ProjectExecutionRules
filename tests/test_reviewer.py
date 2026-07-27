from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_execution_rules.doctor import CommandResult
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.paths import UserPaths
from project_execution_rules.reviewer import review_rules


def test_reviewer_invokes_ephemeral_read_only_codex(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# Router\n", encoding="utf-8")
    (root / ".rules").mkdir()
    (root / ".rules" / "ruleset.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    (root / "business.py").write_text("SECRET = 'must-not-be-mounted'\n", encoding="utf-8")
    paths = UserPaths.from_environment(
        {"LOCALAPPDATA": str(tmp_path / "local")},
        tmp_path / "home",
    )
    captured: list[tuple[tuple[str, ...], str]] = []

    def runner(
        command: tuple[str, ...],
        prompt: str,
        output_path: Path,
    ) -> CommandResult:
        captured.append((command, prompt))
        review_root = Path(command[command.index("--cd") + 1])
        assert (review_root / "project" / "AGENTS.md").is_file()
        assert (review_root / "project" / ".rules" / "ruleset.yaml").is_file()
        assert not (review_root / "business.py").exists()
        assert review_root != root.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps({"status": "pass", "issues": []}),
            encoding="utf-8",
        )
        return CommandResult(0, "", "")

    report = review_rules(root, paths, runner=runner)

    command, prompt = captured[0]
    assert report.status == "pass"
    assert "--ephemeral" in command
    assert (command[command.index("--sandbox") : command.index("--sandbox") + 2]) == (
        "--sandbox",
        "read-only",
    )
    assert "不得审计业务代码" in prompt


def test_reviewer_rejects_invalid_structured_output(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    paths = UserPaths.from_environment({}, tmp_path / "home")

    def runner(
        command: tuple[str, ...],
        prompt: str,
        output_path: Path,
    ) -> CommandResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text('{"status": "unknown"}', encoding="utf-8")
        return CommandResult(0, "", "")

    with pytest.raises(ProjectRulesError, match="invalid review report"):
        review_rules(root, paths, runner=runner)
