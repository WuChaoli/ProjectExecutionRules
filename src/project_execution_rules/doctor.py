from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from project_execution_rules.models import CheckIssue, CheckReport, ProjectState
from project_execution_rules.paths import UserPaths


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[tuple[str, ...]], CommandResult]


def _real_symlink_probe(paths: UserPaths) -> bool:
    paths.state_home.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=paths.state_home) as raw:
        probe = Path(raw)
        source = probe / "source"
        link = probe / "link"
        source.write_text("probe", encoding="utf-8")
        try:
            os.symlink(source, link)
        except OSError:
            return False
        return link.is_symlink() and link.resolve() == source.resolve()


def run_doctor(
    root: Path,
    paths: UserPaths,
    runner: CommandRunner,
    *,
    symlink_probe: Callable[[], bool] | None = None,
) -> CheckReport:
    issues: list[CheckIssue] = []
    if not (root / ".git").exists():
        issues.append(
            CheckIssue(
                code="GIT_REPOSITORY_MISSING",
                message="target root is not a Git repository",
                remediation="Initialize Git before project-rules init.",
            )
        )
    for name in ("git", "codex"):
        result = runner((name, "--version"))
        if result.returncode != 0:
            issues.append(
                CheckIssue(
                    code=f"{name.upper()}_UNAVAILABLE",
                    message=f"{name} CLI is unavailable",
                    evidence={"stderr": result.stderr},
                    remediation=f"Install {name} and ensure it is available on PATH.",
                )
            )
    probe = symlink_probe or (lambda: _real_symlink_probe(paths))
    if not probe():
        issues.append(
            CheckIssue(
                code="SYMLINK_UNAVAILABLE",
                message="Windows symbolic link creation is unavailable",
                remediation="Enable Windows Developer Mode or grant link privileges.",
            )
        )
    return CheckReport(
        state=ProjectState.HEALTHY if not issues else ProjectState.DRIFTED,
        issues=tuple(issues),
    )
