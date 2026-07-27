from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ProjectRulesError(RuntimeError):
    """Base error with stable machine-readable fields."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        evidence: Mapping[str, Any] | None = None,
        remediation: str = "",
        exit_code: int = 1,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.evidence = dict(evidence or {})
        self.remediation = remediation
        self.exit_code = exit_code

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "evidence": self.evidence,
            "remediation": self.remediation,
        }


class TransactionError(ProjectRulesError):
    """A managed filesystem transaction failed."""
