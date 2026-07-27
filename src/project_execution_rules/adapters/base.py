from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from project_execution_rules.commands import CommandResult
from project_execution_rules.detection import ProjectFacts
from project_execution_rules.initialize import ProjectSelection
from project_execution_rules.models import (
    AdapterId,
    ChangePlan,
    RuleCatalog,
)
from project_execution_rules.paths import UserPaths
from project_execution_rules.selection import CatalogSelection


@dataclass(frozen=True, slots=True)
class AdapterDetection:
    adapter: AdapterId
    command: str
    available: bool


class Adapter(Protocol):
    @property
    def id(self) -> AdapterId: ...

    def detect(self, runner: CommandRunner) -> AdapterDetection: ...

    def plan_install(
        self,
        paths: UserPaths,
        catalog: RuleCatalog,
        selection: CatalogSelection,
        *,
        allow_managed_drift: bool = False,
    ) -> ChangePlan: ...

    def plan_project_init(
        self,
        root: Path,
        facts: ProjectFacts,
        selection: ProjectSelection,
        paths: UserPaths,
        *,
        verify_user_install: bool = True,
    ) -> ChangePlan: ...


class CommandRunner(Protocol):
    def __call__(self, command: tuple[str, ...]) -> CommandResult: ...
