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


def test_canonical_resources_exist_at_declared_paths() -> None:
    catalog = load_builtin_catalog()

    for definition in catalog.skills.values():
        assert resource_root().joinpath(definition.file).is_file(), definition.skill_id
    for definition in catalog.agents.values():
        assert resource_root().joinpath(definition.file).is_file(), definition.agent_id


def test_codex_adapter_contains_all_explicit_governance_entries() -> None:
    skills = resource_root().joinpath("adapters/codex/skills")

    for name in ("agent-governance", "tool-governance", "rules-reviewer"):
        assert skills.joinpath(name, "SKILL.md").is_file()
    assert resource_root().joinpath("adapters/codex/agents/rules-reviewer.toml").is_file()
