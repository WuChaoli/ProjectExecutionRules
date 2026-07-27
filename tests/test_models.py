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


def test_activation_requires_exact_trigger_fields() -> None:
    invalid = (
        (ActivationType.ALWAYS, {"paths": ("**/*.py",)}),
        (ActivationType.PATHS, {"paths": ()}),
        (ActivationType.PATHS, {"paths": ("**/*.py",), "tasks": ("test",)}),
        (ActivationType.TASK, {"tasks": ()}),
        (ActivationType.TASK, {"tasks": ("test",), "commands": ("check",)}),
        (ActivationType.EXPLICIT, {"commands": ()}),
        (ActivationType.EXPLICIT, {"commands": ("check",), "paths": ("*.py",)}),
    )

    for activation, fields in invalid:
        with pytest.raises(ValueError, match="activation"):
            RuleDefinition(
                domain="example",
                file="core/example.md",
                activation=activation,
                paths=fields.get("paths", ()),
                tasks=fields.get("tasks", ()),
                commands=fields.get("commands", ()),
            )


def test_check_report_serializes_stable_json() -> None:
    report = CheckReport(state=ProjectState.HEALTHY, issues=())

    assert report.to_dict() == {"state": "healthy", "issues": []}
