from __future__ import annotations

import os
from pathlib import Path

import pytest

from project_execution_rules.commands import run_command


@pytest.mark.skipif(os.name != "nt", reason="Windows command wrappers are platform-specific")
def test_run_command_resolves_windows_command_wrapper_from_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper = tmp_path / "sample-tool.cmd"
    wrapper.write_text("@echo off\r\necho sample-tool 1.0\r\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path))

    result = run_command(("sample-tool", "--version"))

    assert result.returncode == 0
    assert result.stdout.strip() == "sample-tool 1.0"


def test_run_command_returns_unavailable_result_for_missing_command() -> None:
    result = run_command(("project-rules-command-that-does-not-exist", "--version"))

    assert result.returncode == 127
    assert "project-rules-command-that-does-not-exist" in result.stderr
