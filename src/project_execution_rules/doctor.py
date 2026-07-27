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


def probe_symlink_capability(paths: UserPaths) -> bool:
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
    codex_config = root / ".codex" / "config.toml"
    if not codex_config.is_file():
        issues.append(
            CheckIssue(
                code="CODEX_CONFIG_MISSING",
                message="project-local .codex/config.toml is not present",
                severity="warning",
                remediation="Add it only if the project needs explicit Codex configuration.",
            )
        )
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
    probe = symlink_probe or (lambda: probe_symlink_capability(paths))
    if not probe():
        issues.append(
            CheckIssue(
                code="SYMLINK_UNAVAILABLE",
                message="Windows symbolic link creation is unavailable",
                remediation="Enable Windows Developer Mode or grant link privileges.",
            )
        )
    has_errors = any(issue.severity == "error" for issue in issues)
    return CheckReport(
        state=ProjectState.DRIFTED if has_errors else ProjectState.HEALTHY,
        issues=tuple(issues),
    )
