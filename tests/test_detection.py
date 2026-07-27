from __future__ import annotations

from pathlib import Path

from project_execution_rules.detection import detect_project


def test_detects_uv_python_project_without_running_commands(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )

    facts = detect_project(tmp_path)

    assert facts.is_git
    assert facts.profile == "python"
    assert facts.package_manager == "uv"
    assert facts.python_requirement == ">=3.11"
    assert facts.lock_files == ("uv.lock",)
    assert facts.has_tests


def test_detects_poetry_from_lock_file(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "sample"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "poetry.lock").write_text("", encoding="utf-8")

    facts = detect_project(tmp_path)

    assert facts.package_manager == "poetry"
    assert facts.profile == "python"
