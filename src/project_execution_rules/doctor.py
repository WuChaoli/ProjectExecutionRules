from __future__ import annotations

import os
import platform
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.managed import ManagedManifest, sha256_bytes
from project_execution_rules.models import CheckIssue, CheckReport, ProjectState
from project_execution_rules.paths import UserPaths
from project_execution_rules.yaml_utils import load_mapping


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
    if platform.system() != "Windows":
        issues.append(
            CheckIssue(
                code="PLATFORM_UNSUPPORTED",
                message="the first release supports Windows only",
            )
        )
    python_version = tuple(int(part) for part in platform.python_version_tuple()[:2])
    if python_version < (3, 11):
        issues.append(
            CheckIssue(
                code="PYTHON_UNSUPPORTED",
                message="Python 3.11 or newer is required",
            )
        )
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
    manifest_path = paths.state_home / "managed-user.json"
    if not manifest_path.is_file():
        issues.append(
            CheckIssue(
                code="USER_INSTALL_MISSING",
                message="user-level Rules resources are not installed",
                severity="warning",
                remediation="Run project-rules install before initializing a project.",
            )
        )
    else:
        try:
            manifest = ManagedManifest.load(manifest_path)
            for entry in manifest.entries:
                target = paths.home / entry.logical_path
                try:
                    target.absolute().relative_to(paths.home.resolve())
                    target.parent.resolve(strict=False).relative_to(paths.home.resolve())
                except ValueError:
                    issues.append(
                        CheckIssue(
                            code="MANAGED_RESOURCE_PATH_INVALID",
                            message=(
                                f"managed resource path escapes the user home: {entry.logical_path}"
                            ),
                        )
                    )
                    continue
                if (
                    target.is_symlink()
                    or not target.is_file()
                    or sha256_bytes(target.read_bytes()) != entry.sha256
                ):
                    issues.append(
                        CheckIssue(
                            code="MANAGED_RESOURCE_DRIFTED",
                            message=(
                                "managed user resource is missing or modified: "
                                f"{entry.logical_path}"
                            ),
                        )
                    )
        except (OSError, ValueError, TypeError, KeyError, ProjectRulesError) as error:
            issues.append(
                CheckIssue(
                    code="MANAGED_MANIFEST_INVALID",
                    message=f"user resource manifest is invalid: {error}",
                )
            )
    if paths.transactions_home.is_dir() and any(paths.transactions_home.iterdir()):
        issues.append(
            CheckIssue(
                code="TRANSACTION_INCOMPLETE",
                message="one or more incomplete transactions require recovery",
                remediation="Inspect the transaction IDs and run project-rules rollback.",
            )
        )
    ruleset_path = root / ".rules" / "ruleset.yaml"
    if ruleset_path.is_file():
        try:
            ruleset = load_mapping(ruleset_path.read_text(encoding="utf-8"), name="Rule Set")
            if ruleset.get("schema_version") != 1:
                issues.append(
                    CheckIssue(
                        code="RULESET_SCHEMA_INCOMPATIBLE",
                        message="project Rule Set schema is not supported",
                    )
                )
        except (OSError, ValueError) as error:
            issues.append(
                CheckIssue(
                    code="RULESET_INVALID",
                    message=f"project Rule Set is invalid: {error}",
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
