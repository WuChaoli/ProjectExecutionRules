from __future__ import annotations

from pathlib import Path

from project_execution_rules.adapters import (
    get_adapter,
    normalize_adapters,
    registered_adapter_ids,
)
from project_execution_rules.models import AdapterId


def test_registry_order_is_codex_then_claude() -> None:
    assert registered_adapter_ids() == (AdapterId.CODEX, AdapterId.CLAUDE)


def test_registry_resolves_registered_adapters() -> None:
    assert get_adapter(AdapterId.CODEX).id is AdapterId.CODEX
    assert get_adapter("claude").id is AdapterId.CLAUDE


def test_normalize_adapters_preserves_registry_order() -> None:
    assert normalize_adapters(("claude", "codex")) == (
        AdapterId.CODEX,
        AdapterId.CLAUDE,
    )


def test_adapter_protocol_exposes_planning_methods() -> None:
    adapter = get_adapter(AdapterId.CODEX)

    assert callable(adapter.plan_install)
    assert callable(adapter.plan_project_init)
    assert isinstance(Path("."), Path)
