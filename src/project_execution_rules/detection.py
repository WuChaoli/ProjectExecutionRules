from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProjectFacts:
    root: Path
    is_git: bool
    profile: str
    package_manager: str
    python_requirement: str
    lock_files: tuple[str, ...]
    has_tests: bool
    has_ci: bool
    source_dirs: tuple[str, ...]


def detect_project(root: Path) -> ProjectFacts:
    resolved = root.resolve()
    pyproject = resolved / "pyproject.toml"
    metadata: dict[str, object] = {}
    if pyproject.is_file():
        metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = metadata.get("project", {})
    if not isinstance(project, dict):
        project = {}
    lock_files = tuple(
        name for name in ("uv.lock", "poetry.lock", "Pipfile.lock") if (resolved / name).is_file()
    )
    if "uv.lock" in lock_files:
        manager = "uv"
    elif "poetry.lock" in lock_files or (
        isinstance(metadata.get("tool"), dict) and isinstance(metadata["tool"].get("poetry"), dict)  # type: ignore[union-attr]
    ):
        manager = "poetry"
    elif "Pipfile.lock" in lock_files:
        manager = "pipenv"
    else:
        manager = "unknown"
    source_dirs = tuple(name for name in ("src", "app", "lib") if (resolved / name).is_dir())
    return ProjectFacts(
        root=resolved,
        is_git=(resolved / ".git").exists(),
        profile="python" if pyproject.is_file() else "unknown",
        package_manager=manager,
        python_requirement=str(project.get("requires-python", "")),
        lock_files=lock_files,
        has_tests=(resolved / "tests").is_dir() or (resolved / "test").is_dir(),
        has_ci=(resolved / ".github" / "workflows").is_dir()
        or (resolved / ".gitlab-ci.yml").is_file(),
        source_dirs=source_dirs,
    )
