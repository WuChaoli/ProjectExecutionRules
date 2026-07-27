from __future__ import annotations

from project_execution_rules.catalog import load_builtin_catalog, resource_root
from project_execution_rules.frontmatter import parse_frontmatter


def test_parse_frontmatter_separates_metadata_and_body() -> None:
    metadata, body = parse_frontmatter('---\npaths:\n  - "**/*.py"\n---\n\n# Python Rules\n')

    assert metadata == {"paths": ["**/*.py"]}
    assert body.startswith("# Python Rules")


def test_builtin_rules_use_stable_contract_sections() -> None:
    catalog = load_builtin_catalog()

    for definition in catalog.rules.values():
        text = resource_root().joinpath("rules", definition.file).read_text(encoding="utf-8")
        _, body = parse_frontmatter(text)
        assert all(
            section in body for section in ("## WHEN", "## MUST", "## MUST NOT")
        ), definition.domain
        assert not any(
            heading in body
            for heading in ("## 事实来源", "## 执行规则", "## 验证要求", "## 职责边界")
        ), definition.domain


def test_task_and_explicit_rules_describe_dependencies() -> None:
    catalog = load_builtin_catalog()
    expected = {
        "git": ("git",),
        "pull-request": ("pull-request",),
        "debug": ("debug",),
        "observability": ("observability",),
        "architecture": ("architecture",),
        "external-services": ("external-services",),
        "agent": ("agent-governance",),
        "tool": ("tool-governance",),
        "harness": ("rules-reviewer",),
    }
    for domain, skills in expected.items():
        definition = catalog.rules[domain]
        body = resource_root().joinpath("rules", definition.file).read_text(encoding="utf-8")
        for skill_id in skills:
            assert skill_id in body, (domain, skill_id)
        if definition.agents:
            for agent_id in definition.agents:
                assert agent_id in body, (domain, agent_id)


def test_pull_request_rule_preserves_pr_002_clause() -> None:
    catalog = load_builtin_catalog()
    text = resource_root().joinpath("rules", catalog.rules["pull-request"].file).read_text(
        encoding="utf-8"
    )

    assert "- `PR-002`：PR 描述必须说明范围、验证证据、风险和未确认边界。" in text



    catalog = load_builtin_catalog()

    for definition in catalog.skills.values():
        assert resource_root().joinpath(definition.file).is_file(), definition.skill_id
    for definition in catalog.agents.values():
        assert resource_root().joinpath(definition.file).is_file(), definition.agent_id


def test_claude_adapter_templates_are_packaged() -> None:
    templates = resource_root().joinpath("adapters/claude/templates")

    for name in ("rule.md.j2", "skill.md.j2", "agent.md.j2"):
        assert templates.joinpath(name).is_file(), name


def test_codex_adapter_contains_all_explicit_governance_entries() -> None:
    skills = resource_root().joinpath("adapters/codex/skills")

    for name in ("agent-governance", "tool-governance", "rules-reviewer"):
        assert skills.joinpath(name, "SKILL.md").is_file()
    assert resource_root().joinpath("adapters/codex/agents/rules-reviewer.toml").is_file()
