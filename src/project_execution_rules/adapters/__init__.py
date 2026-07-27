from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from project_execution_rules.adapters.base import Adapter, AdapterDetection, CommandRunner
from project_execution_rules.adapters.codex import CodexAdapter
from project_execution_rules.detection import ProjectFacts
from project_execution_rules.initialize import ProjectSelection
from project_execution_rules.models import AdapterId, ChangePlan, RuleCatalog
from project_execution_rules.paths import UserPaths
from project_execution_rules.selection import CatalogSelection


@dataclass(frozen=True, slots=True)
class _PlaceholderAdapter:
    _id: AdapterId
    command: str

    @property
    def id(self) -> AdapterId:
        return self._id

    def detect(self, runner: CommandRunner) -> AdapterDetection:
        result = runner((self.command, "--version"))
        return AdapterDetection(self.id, self.command, result.returncode == 0)

    def plan_install(
        self,
        paths: UserPaths,
        catalog: RuleCatalog,
        selection: CatalogSelection,
        *,
        allow_managed_drift: bool = False,
    ) -> ChangePlan:
        return ChangePlan(scope=f"user:{self.id.value}", changes=())

    def plan_project_init(
        self,
        root: Path,
        facts: ProjectFacts,
        selection: ProjectSelection,
        paths: UserPaths,
        *,
        verify_user_install: bool = True,
    ) -> ChangePlan:
        return ChangePlan(scope=f"project:{self.id.value}", changes=())


_ADAPTERS: Mapping[AdapterId, Adapter] = {
    AdapterId.CODEX: CodexAdapter(),
    AdapterId.CLAUDE: _PlaceholderAdapter(AdapterId.CLAUDE, "claude"),
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
