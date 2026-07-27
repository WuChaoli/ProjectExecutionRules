from __future__ import annotations

from project_execution_rules.catalog import load_builtin_catalog, validate_catalog_resources
from project_execution_rules.models import ActivationType, AdapterId, RuleCatalog, RuleDefinition


def test_catalog_v2_resolves_rule_dependencies() -> None:
    catalog = load_builtin_catalog()

    assert catalog.schema_version == 2
    assert catalog.rules["pull-request"].skills == ("pull-request",)
    assert "pull-request" in catalog.skills
    assert "rules-reviewer" in catalog.agents


def test_catalog_validation_rejects_missing_and_self_references() -> None:
    catalog = RuleCatalog(
        schema_version=2,
        rules_version="2.0.0",
        rules={
            "example": RuleDefinition(
                domain="example",
                file="core/security-rules.md",
                activation=ActivationType.ALWAYS,
                skills=("missing",),
                agents=("example",),
            )
        },
        profiles={},
        skills={},
        agents={},
    )

    codes = {issue.code for issue in validate_catalog_resources(catalog)}
    assert "RULE_SKILL_MISSING" in codes
    assert "RULE_AGENT_MISSING" in codes


def test_user_invocation_skill_cannot_be_preloaded() -> None:
    catalog = load_builtin_catalog()
    issues = validate_catalog_resources(catalog)

    assert not any(issue.code == "AGENT_SKILL_INVOCATION_INVALID" for issue in issues)


    catalog = load_builtin_catalog()

    assert len([rule for rule in catalog.rules.values() if rule.core]) == 13
    assert catalog.profiles["python"] == ("python",)
    assert catalog.rules["python"].activation is ActivationType.PATHS


def test_task_and_explicit_rules_are_not_path_scoped() -> None:
    catalog = load_builtin_catalog()

    assert catalog.rules["git"].activation is ActivationType.TASK
    assert catalog.rules["git"].paths == ()
    assert catalog.rules["harness"].activation is ActivationType.EXPLICIT
    assert catalog.rules["harness"].paths == ()


def test_pull_request_review_trigger_is_namespaced() -> None:
    tasks = load_builtin_catalog().rules["pull-request"].tasks

    assert "pull-request-review" in tasks
    assert "review" not in tasks
