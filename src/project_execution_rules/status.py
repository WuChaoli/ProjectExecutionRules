from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from project_execution_rules.checker import check_project
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.models import AdapterId, CheckReport, ProjectState
from project_execution_rules.paths import UserPaths
from project_execution_rules.rulesets import load_ruleset


@dataclass(frozen=True, slots=True)
class StatusReport:
    state: ProjectState
    profile: str | None
    rules_version: str | None
    issue_count: int
    adapters: tuple[AdapterId, ...]
    adapter_issue_counts: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "profile": self.profile,
            "rules_version": self.rules_version,
            "issue_count": self.issue_count,
            "adapters": [adapter.value for adapter in self.adapters],
            "adapter_issue_counts": dict(self.adapter_issue_counts),
        }


CheckRunner = Callable[[Path, UserPaths], object]


def get_project_status(
    root: Path,
    paths: UserPaths,
    *,
    check_runner: Callable[[Path, UserPaths], CheckReport] | None = None,
) -> StatusReport:
    resolved = root.resolve()
    check = (
        check_project(resolved, paths) if check_runner is None else check_runner(resolved, paths)
    )
    ruleset_path = resolved / ".rules" / "ruleset.yaml"
    try:
        ruleset = load_ruleset(ruleset_path) if ruleset_path.is_file() else None
    except ProjectRulesError:
        ruleset = None
    adapters = () if ruleset is None else ruleset.adapters
    counts = {adapter.value: 0 for adapter in adapters}
    for issue in check.issues:
        adapter = issue.evidence.get("adapter")
        if isinstance(adapter, str) and adapter in counts:
            counts[adapter] += 1
    return StatusReport(
        state=check.state,
        profile=None if ruleset is None else ruleset.profile,
        rules_version=None if ruleset is None else ruleset.rules_version,
        issue_count=len(check.issues),
        adapters=adapters,
        adapter_issue_counts=counts,
    )
