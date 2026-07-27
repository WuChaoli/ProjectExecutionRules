from __future__ import annotations

from pathlib import Path

from project_execution_rules.paths import UserPaths


def test_user_paths_use_local_app_data(tmp_path: Path) -> None:
    paths = UserPaths.from_environment(
        {"LOCALAPPDATA": str(tmp_path / "local")},
        tmp_path / "home",
    )

    assert paths.state_home == tmp_path / "local" / "ProjectExecutionRules"
    assert paths.rules_home == tmp_path / "home" / ".agents" / "rules"
    assert paths.codex_agents == tmp_path / "home" / ".codex" / "agents"


def test_user_paths_fall_back_to_home_app_data(tmp_path: Path) -> None:
    paths = UserPaths.from_environment({}, tmp_path / "home")

    assert paths.state_home == (tmp_path / "home" / "AppData" / "Local" / "ProjectExecutionRules")
