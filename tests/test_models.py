from __future__ import annotations

import pytest

from project_execution_rules.models import (
    ActivationType,
    AdapterId,
    AgentDefinition,
    CheckReport,
    ProjectState,
    RuleDefinition,
    SkillDefinition,
    SkillInvocation,
)


def test_v2_resource_definitions_are_typed() -> None:
    skill = SkillDefinition(
        skill_id="pull-request",
        file="skills/pull-request/SKILL.md",
        invocation=SkillInvocation.MODEL,
        adapters=(AdapterId.CODEX, AdapterId.CLAUDE),
    )
    agent = AgentDefinition(
        agent_id="rules-reviewer",
        file="agents/rules-reviewer.md",
        skills=("pull-request",),
        adapters=(AdapterId.CLAUDE,),
    )

    assert skill.invocation is SkillInvocation.MODEL
    assert agent.adapters == (AdapterId.CLAUDE,)


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
