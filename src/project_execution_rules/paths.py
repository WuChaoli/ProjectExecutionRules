from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from project_execution_rules.models import AdapterId


@dataclass(frozen=True, slots=True)
class UserPaths:
    home: Path
    rules_home: Path
    codex_agents: Path
    codex_skills: Path
    claude_home: Path
    claude_rules: Path
    claude_skills: Path
    claude_agents: Path
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
            claude_home=resolved_home / ".claude",
            claude_rules=resolved_home / ".claude" / "rules",
            claude_skills=resolved_home / ".claude" / "skills",
            claude_agents=resolved_home / ".claude" / "agents",
            state_home=state_home,
            transactions_home=state_home / "transactions",
            backups_home=state_home / "backups",
            registry_file=state_home / "registry.json",
        )

    def manifest_path(self, adapter: AdapterId | str) -> Path:
        adapter_id = AdapterId(adapter)
        return self.state_home / f"managed-user-{adapter_id.value}.json"
