from __future__ import annotations

import pytest

from project_execution_rules.models import (
    ActivationType,
    CheckReport,
    ProjectState,
    RuleDefinition,
)


def test_rule_definition_rejects_parent_path() -> None:
    with pytest.raises(ValueError, match="project-relative"):
        RuleDefinition(
            domain="python",
            file="profiles/python/python-rules.md",
            activation=ActivationType.PATHS,
            paths=("../secret",),
        )


def test_paths_activation_requires_at_least_one_pattern() -> None:
    with pytest.raises(ValueError, match="requires paths"):
        RuleDefinition(
            domain="python",
            file="profiles/python/python-rules.md",
            activation=ActivationType.PATHS,
        )


def test_check_report_serializes_stable_json() -> None:
    report = CheckReport(state=ProjectState.HEALTHY, issues=())

    assert report.to_dict() == {"state": "healthy", "issues": []}
