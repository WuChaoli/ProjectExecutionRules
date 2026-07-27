from dataclasses import replace

import pytest

from project_execution_rules.catalog import load_builtin_catalog
from project_execution_rules.models import AdapterId
from project_execution_rules.selection import resolve_catalog_selection


def test_selection_adds_transitive_skill_and_agent_dependencies() -> None:
    selection = resolve_catalog_selection(load_builtin_catalog(), ("pull-request",))

    assert selection.rules == ("pull-request",)
    assert selection.skills == ("pull-request",)
    assert selection.agents == ("rules-reviewer",)


def test_selection_rejects_unsupported_adapter_dependency() -> None:
    catalog = load_builtin_catalog()
    catalog.skills["pull-request"] = replace(
        catalog.skills["pull-request"], adapters=(AdapterId.CODEX,)
    )

    with pytest.raises(ValueError, match="claude"):
        resolve_catalog_selection(
            catalog,
            ("pull-request",),
            adapter=AdapterId.CLAUDE,
        )


def test_selection_rejects_unknown_rule() -> None:
    with pytest.raises(ValueError, match="unknown Rule"):
        resolve_catalog_selection(load_builtin_catalog(), ("missing",))
