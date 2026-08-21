from __future__ import annotations

from collections.abc import Mapping

from project_execution_rules.adapters.base import Adapter, AdapterDetection
from project_execution_rules.adapters.claude import ClaudeAdapter
from project_execution_rules.adapters.codex import CodexAdapter
from project_execution_rules.models import AdapterId

_ADAPTERS: Mapping[AdapterId, Adapter] = {
    AdapterId.CODEX: CodexAdapter(),
    AdapterId.CLAUDE: ClaudeAdapter(),
}


def registered_adapter_ids() -> tuple[AdapterId, ...]:
    return tuple(_ADAPTERS)


def get_adapter(adapter: AdapterId | str) -> Adapter:
    adapter_id = AdapterId(adapter)
    try:
        return _ADAPTERS[adapter_id]
    except KeyError as error:
        raise ValueError(f"unknown Adapter: {adapter}") from error


def normalize_adapters(adapters: tuple[AdapterId | str, ...]) -> tuple[AdapterId, ...]:
    requested = {AdapterId(adapter) for adapter in adapters}
    return tuple(adapter for adapter in registered_adapter_ids() if adapter in requested)


__all__ = [
    "Adapter",
    "AdapterDetection",
    "get_adapter",
    "normalize_adapters",
    "registered_adapter_ids",
]
