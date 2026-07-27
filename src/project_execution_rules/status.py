from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from project_execution_rules.checker import check_project
from project_execution_rules.models import ProjectState
from project_execution_rules.paths import UserPaths


@dataclass(frozen=True, slots=True)
class StatusReport:
    state: ProjectState
    profile: str | None
    rules_version: str | None
    issue_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "profile": self.profile,
            "rules_version": self.rules_version,
            "issue_count": self.issue_count,
        }


def get_project_status(root: Path, paths: UserPaths) -> StatusReport:
    check = check_project(root, paths)
    ruleset = root / ".rules" / "ruleset.yaml"
    raw = yaml.safe_load(ruleset.read_text(encoding="utf-8")) if ruleset.is_file() else {}
    if not isinstance(raw, dict):
        raw = {}
    return StatusReport(
        state=check.state,
        profile=str(raw["profile"]) if "profile" in raw else None,
        rules_version=str(raw["rules_version"]) if "rules_version" in raw else None,
        issue_count=len(check.issues),
    )
