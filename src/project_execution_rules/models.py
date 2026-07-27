from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any


class ActivationType(StrEnum):
    ALWAYS = "always"
    PATHS = "paths"
    TASK = "task"
    EXPLICIT = "explicit"


class ProjectState(StrEnum):
    UNMANAGED = "unmanaged"
    PLANNED = "planned"
    HEALTHY = "healthy"
    DRIFTED = "drifted"
    UPDATE_AVAILABLE = "update_available"
    INCOMPATIBLE = "incompatible"


class OutputFormat(StrEnum):
    HUMAN = "human"
    JSON = "json"


@dataclass(frozen=True, slots=True)
class Change:
    action: str
    target: Path
    content: bytes = b""
    link_target: Path | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "target": str(self.target),
            "link_target": str(self.link_target) if self.link_target else None,
        }


@dataclass(frozen=True, slots=True)
class ChangePlan:
    scope: str
    changes: tuple[Change, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "changes": [change.to_dict() for change in self.changes],
        }


@dataclass(frozen=True, slots=True)
class OperationReport:
    changed: bool
    transaction_id: str | None
    changes: tuple[Change, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "changed": self.changed,
            "transaction_id": self.transaction_id,
            "changes": [change.to_dict() for change in self.changes],
        }


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    domain: str
    file: str
    activation: ActivationType
    paths: tuple[str, ...] = ()
    tasks: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    core: bool = True
    required: bool = False

    def __post_init__(self) -> None:
        if not self.domain or "/" in self.domain or "\\" in self.domain:
            raise ValueError("domain must be a simple identifier")
        if self.activation is ActivationType.PATHS and not self.paths:
            raise ValueError("paths activation requires paths")
        for pattern in self.paths:
            normalized = pattern.replace("\\", "/")
            path = PurePosixPath(normalized)
            if (
                not normalized
                or path.is_absolute()
                or ".." in path.parts
                or (len(normalized) >= 2 and normalized[1] == ":")
            ):
                raise ValueError(f"path must be project-relative: {pattern}")


@dataclass(frozen=True, slots=True)
class RuleCatalog:
    schema_version: int
    rules_version: str
    rules: dict[str, RuleDefinition]
    profiles: dict[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class RuleSet:
    schema_version: int
    rules_version: str
    adapter: str
    profile: str
    core_domains: tuple[str, ...]
    profile_domains: tuple[str, ...]
    overrides: tuple[str, ...] = ()

    @property
    def domains(self) -> tuple[str, ...]:
        return self.core_domains + self.profile_domains


@dataclass(frozen=True, slots=True)
class CheckIssue:
    code: str
    message: str
    severity: str = "error"
    evidence: dict[str, Any] = field(default_factory=dict)
    remediation: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "evidence": self.evidence,
            "remediation": self.remediation,
        }


@dataclass(frozen=True, slots=True)
class CheckReport:
    state: ProjectState
    issues: tuple[CheckIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues and self.state is ProjectState.HEALTHY

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "issues": [issue.to_dict() for issue in self.issues],
        }
