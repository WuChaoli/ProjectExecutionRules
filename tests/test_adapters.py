from __future__ import annotations

from pathlib import Path

from project_execution_rules.adapters import (
    get_adapter,
    normalize_adapters,
    registered_adapter_ids,
)
from project_execution_rules.catalog import load_builtin_catalog
from project_execution_rules.commands import CommandResult
from project_execution_rules.detection import detect_project
from project_execution_rules.initialize import ProjectSelection
from project_execution_rules.models import AdapterId
from project_execution_rules.paths import UserPaths
from project_execution_rules.selection import resolve_catalog_selection


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


def test_codex_adapter_detects_cli() -> None:
    detection = get_adapter(AdapterId.CODEX).detect(
        lambda command: CommandResult(0, "codex 1.0", "")
    )

    assert detection.adapter is AdapterId.CODEX
    assert detection.command == "codex"
    assert detection.available


def test_codex_adapter_plans_real_install_targets(tmp_path: Path) -> None:
    catalog = load_builtin_catalog()
    selection = resolve_catalog_selection(catalog, catalog.rules, adapter=AdapterId.CODEX)
    paths = UserPaths.from_environment({}, tmp_path / "home")

    plan = get_adapter(AdapterId.CODEX).plan_install(paths, catalog, selection)

    targets = {change.target for change in plan.changes}
    assert plan.scope == "user:codex"
    assert paths.rules_home / "security-rules.md" in targets
    assert paths.codex_agents / "rules-reviewer.toml" in targets
    assert paths.manifest_path(AdapterId.CODEX) in targets


def test_codex_adapter_plans_base_links_and_guide(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    paths = UserPaths.from_environment({}, tmp_path / "home")
    (paths.rules_home).mkdir(parents=True)
    for domain in ("security", "python"):
        (paths.rules_home / f"{domain}-rules.md").write_text(
            f"{domain}\n", encoding="utf-8"
        )

    plan = get_adapter(AdapterId.CODEX).plan_project_init(
        root,
        detect_project(root),
        ProjectSelection(core_domains=("security",)),
        paths,
    )

    targets = {change.target for change in plan.changes}
    assert plan.scope == "project:codex"
    assert root / ".rules" / "security-rules.md" in targets
    assert root / "AGENTS.md" in targets
    assert root / ".gitignore" in targets
