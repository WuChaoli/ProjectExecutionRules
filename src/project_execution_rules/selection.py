from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from project_execution_rules.models import AdapterId, RuleCatalog


@dataclass(frozen=True, slots=True)
class CatalogSelection:
    rules: tuple[str, ...]
    skills: tuple[str, ...]
    agents: tuple[str, ...]


def _append_unique(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)


def resolve_catalog_selection(
    catalog: RuleCatalog,
    rule_ids: Iterable[str],
    *,
    adapter: AdapterId | str | None = None,
) -> CatalogSelection:
    rules: list[str] = []
    skills: list[str] = []
    agents: list[str] = []
    for rule_id in rule_ids:
        if rule_id not in catalog.rules:
            raise ValueError(f"unknown Rule: {rule_id}")
        _append_unique(rules, rule_id)

    for rule_id in rules:
        rule = catalog.rules[rule_id]
        for skill_id in rule.skills:
            if skill_id not in catalog.skills:
                raise ValueError(f"Rule {rule_id} references unknown Skill: {skill_id}")
            _append_unique(skills, skill_id)
        for agent_id in rule.agents:
            if agent_id not in catalog.agents:
                raise ValueError(f"Rule {rule_id} references unknown Agent: {agent_id}")
            _append_unique(agents, agent_id)

    for agent_id in agents:
        for skill_id in catalog.agents[agent_id].skills:
            if skill_id not in catalog.skills:
                raise ValueError(f"Agent {agent_id} references unknown Skill: {skill_id}")
            _append_unique(skills, skill_id)

    selected_adapter = AdapterId(adapter) if adapter is not None else None
    if selected_adapter is not None:
        for skill_id in skills:
            if selected_adapter not in catalog.skills[skill_id].adapters:
                raise ValueError(
                    f"Skill {skill_id} is not supported by Adapter {selected_adapter.value}"
                )
        for agent_id in agents:
            if selected_adapter not in catalog.agents[agent_id].adapters:
                raise ValueError(
                    f"Agent {agent_id} is not supported by Adapter {selected_adapter.value}"
                )

    return CatalogSelection(tuple(rules), tuple(skills), tuple(agents))
