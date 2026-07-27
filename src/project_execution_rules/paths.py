from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class UserPaths:
    home: Path
    rules_home: Path
    codex_agents: Path
    codex_skills: Path
    state_home: Path
    transactions_home: Path
    backups_home: Path
    registry_file: Path

    @classmethod
    def from_environment(cls, environ: Mapping[str, str], home: Path) -> UserPaths:
        resolved_home = home.resolve()
        local_app_data = Path(
            environ.get("LOCALAPPDATA", str(resolved_home / "AppData" / "Local"))
        ).resolve()
        state_home = local_app_data / "ProjectExecutionRules"
        return cls(
            home=resolved_home,
            rules_home=resolved_home / ".agents" / "rules",
            codex_agents=resolved_home / ".codex" / "agents",
            codex_skills=resolved_home / ".codex" / "skills",
            state_home=state_home,
            transactions_home=state_home / "transactions",
            backups_home=state_home / "backups",
            registry_file=state_home / "registry.json",
        )
