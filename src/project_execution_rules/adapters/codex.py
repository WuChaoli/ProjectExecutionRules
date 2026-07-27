from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from project_execution_rules.adapters.base import AdapterDetection, CommandRunner
from project_execution_rules.catalog import load_builtin_catalog, resource_root
from project_execution_rules.detection import ProjectFacts
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.initialize import ProjectSelection
from project_execution_rules.managed import (
    ManagedEntry,
    ManagedManifest,
    ManagedSelection,
    is_safe_adapter_file,
    is_safe_adapter_path,
    sha256_bytes,
)
from project_execution_rules.models import AdapterId, Change, ChangePlan, RuleCatalog, RuleSet
from project_execution_rules.paths import UserPaths
from project_execution_rules.rulesets import render_ruleset
from project_execution_rules.selection import CatalogSelection
from project_execution_rules.yaml_utils import as_mapping, load_mapping


@dataclass(frozen=True, slots=True)
class CodexAdapter:
    @property
    def id(self) -> AdapterId:
        return AdapterId.CODEX

    def detect(self, runner: CommandRunner) -> AdapterDetection:
        result = runner(("codex", "--version"))
        return AdapterDetection(self.id, "codex", result.returncode == 0)

    def plan_install(
        self,
        paths: UserPaths,
        catalog: RuleCatalog,
        selection: CatalogSelection,
        *,
        allow_managed_drift: bool = False,
    ) -> ChangePlan:
        managed = self._managed_hashes(paths)
        changes: list[Change] = []
        entries: list[ManagedEntry] = []
        for change in self._resource_changes(paths, catalog, selection):
            if not is_safe_adapter_path(change.target, adapter_home=paths.home):
                raise ProjectRulesError(
                    "NON_MANAGED_CONFLICT",
                    f"refusing non-managed unsafe path: {change.target}",
                    evidence={"target": str(change.target)},
                    remediation="Remove the symlink or reparse ancestor, then retry.",
                )
            logical = change.target.relative_to(paths.home).as_posix()
            desired_hash = sha256_bytes(change.content)
            if change.target.exists() or change.target.is_symlink():
                if not is_safe_adapter_file(change.target, adapter_home=paths.home):
                    raise ProjectRulesError(
                        "NON_MANAGED_CONFLICT",
                        f"refusing to overwrite non-managed file: {change.target}",
                        evidence={"target": str(change.target)},
                        remediation="Move or rename the conflicting file, then retry.",
                    )
                current_hash = sha256_bytes(change.target.read_bytes())
                if current_hash == desired_hash:
                    entries.append(
                        ManagedEntry(
                            logical,
                            self._resource_kind(change.target, paths),
                            desired_hash,
                        )
                    )
                    continue
                if managed.get(logical) != current_hash and not (
                    allow_managed_drift and logical in managed
                ):
                    raise ProjectRulesError(
                        "NON_MANAGED_CONFLICT",
                        f"refusing to overwrite non-managed file: {change.target}",
                        evidence={"target": str(change.target)},
                        remediation="Move or rename the conflicting file, then retry.",
                    )
            changes.append(change)
            entries.append(
                ManagedEntry(logical, self._resource_kind(change.target, paths), desired_hash)
            )
        manifest_path = paths.manifest_path(self.id)
        manifest_content = ManagedManifest(
            schema_version=2,
            adapter=self.id,
            resource_version=catalog.rules_version,
            selection=ManagedSelection(
                rules=selection.rules,
                skills=selection.skills,
                agents=selection.agents,
            ),
            entries=tuple(entries),
        ).to_bytes(manifest_path)
        if not manifest_path.is_file() or manifest_path.read_bytes() != manifest_content:
            changes.append(Change(action="write", target=manifest_path, content=manifest_content))
        return ChangePlan(scope="user:codex", changes=tuple(changes))

    def plan_project_init(
        self,
        root: Path,
        facts: ProjectFacts,
        selection: ProjectSelection,
        paths: UserPaths,
    ) -> ChangePlan:
        from project_execution_rules.initialize import (
            append_codex_ignore,
            project_change_required,
        )
        from project_execution_rules.rendering import (
            render_agents,
            render_python_override,
        )

        resolved = root.resolve()
        if not facts.is_git:
            raise ProjectRulesError(
                "GIT_REPOSITORY_MISSING",
                "project initialization requires a Git repository",
            )
        if facts.profile != "python":
            raise ProjectRulesError(
                "PROFILE_UNSUPPORTED",
                "the first release supports Python projects only",
            )
        catalog = load_builtin_catalog()
        domains = selection.core_domains + catalog.profiles["python"]
        for domain in domains:
            if domain not in catalog.rules:
                raise ProjectRulesError("RULE_UNKNOWN", f"unknown Rule domain: {domain}")
            if not (paths.rules_home / f"{domain}-rules.md").is_file():
                raise ProjectRulesError(
                    "USER_RULE_MISSING",
                    f"user Rule is not installed: {domain}",
                )
        rules_dir = resolved / ".rules"
        changes = [
            Change(
                action="symlink",
                target=rules_dir / f"{domain}-rules.md",
                link_target=paths.rules_home / f"{domain}-rules.md",
            )
            for domain in domains
        ]
        for domain in selection.override_domains:
            if domain != "python":
                raise ProjectRulesError(
                    "OVERRIDE_UNSUPPORTED",
                    f"no real project override renderer exists for {domain}",
                )
            changes.append(
                Change(
                    action="write",
                    target=rules_dir / "python-rules.override.md",
                    content=render_python_override(facts).encode(),
                )
            )
        changes.extend(
            (
                Change(
                    action="write",
                    target=rules_dir / "ruleset.yaml",
                    content=render_project_ruleset(selection, catalog).encode(),
                ),
                Change(
                    action="write",
                    target=resolved / "AGENTS.md",
                    content=render_agents(selection).encode(),
                ),
                Change(
                    action="write",
                    target=resolved / ".gitignore",
                    content=append_codex_ignore(
                        (resolved / ".gitignore").read_text(encoding="utf-8")
                        if (resolved / ".gitignore").is_file()
                        else "",
                        domains,
                    ).encode(),
                ),
            )
        )
        return ChangePlan(
            scope="project:codex",
            changes=tuple(change for change in changes if project_change_required(change)),
        )

    def _managed_hashes(self, paths: UserPaths) -> dict[str, str]:
        manifest_path = paths.manifest_path(self.id)
        if not manifest_path.is_file():
            return {}
        manifest = ManagedManifest.load(manifest_path, expected_adapter=self.id)
        return {entry.logical_path: entry.sha256 for entry in manifest.entries}

    def _resource_changes(
        self,
        paths: UserPaths,
        catalog: RuleCatalog,
        selection: CatalogSelection,
    ) -> tuple[Change, ...]:
        root = resource_root()
        changes = [
            Change(
                action="write",
                target=paths.rules_home / f"{domain}-rules.md",
                content=root.joinpath("rules", catalog.rules[domain].file).read_bytes(),
            )
            for domain in selection.rules
        ]
        changes.extend(
            (
                Change(
                    action="write",
                    target=paths.rules_home / "catalog.yaml",
                    content=self._installed_catalog_content(catalog),
                ),
                Change(
                    action="write",
                    target=paths.rules_home / "review-report.schema.json",
                    content=root.joinpath("schemas/review-report.schema.json").read_bytes(),
                ),
            )
        )
        for agent_id in selection.agents:
            changes.append(
                Change(
                    action="write",
                    target=paths.codex_agents / f"{agent_id}.toml",
                    content=root.joinpath(f"adapters/codex/agents/{agent_id}.toml").read_bytes(),
                )
            )
        for skill_id in selection.skills:
            source = root.joinpath(f"adapters/codex/skills/{skill_id}/SKILL.md")
            if source.is_file():
                changes.append(
                    Change(
                        action="write",
                        target=paths.codex_skills / skill_id / "SKILL.md",
                        content=source.read_bytes(),
                    )
                )
        return tuple(changes)

    @staticmethod
    def _installed_catalog_content(catalog: RuleCatalog) -> bytes:
        raw = load_mapping(
            resource_root().joinpath("catalog.yaml").read_text(encoding="utf-8"),
            name="Catalog",
        )
        rules = as_mapping(raw["rules"], name="Catalog rules")
        for domain in catalog.rules:
            rule = as_mapping(rules[domain], name=f"Catalog rule {domain}")
            rule["file"] = f"{domain}-rules.md"
            rules[domain] = rule
        raw["rules"] = rules
        return yaml.safe_dump(raw, allow_unicode=True, sort_keys=False).encode()

    @staticmethod
    def _resource_kind(target: Path, paths: UserPaths) -> str:
        if target.is_relative_to(paths.codex_skills):
            return "skill"
        if target.is_relative_to(paths.codex_agents):
            return "agent"
        return "rule"


def project_ruleset(
    selection: ProjectSelection,
    catalog: RuleCatalog | None = None,
    *,
    adapters: tuple[AdapterId, ...] = (AdapterId.CODEX,),
) -> RuleSet:
    selected_catalog = catalog or load_builtin_catalog()
    return RuleSet(
        schema_version=2,
        rules_version=selected_catalog.rules_version,
        adapters=adapters,
        profile="python",
        core_domains=selection.core_domains,
        profile_domains=selected_catalog.profiles["python"],
        overrides={
            adapter: selection.override_domains if adapter is AdapterId.CODEX else ()
            for adapter in adapters
        },
    )


def render_project_ruleset(
    selection: ProjectSelection,
    catalog: RuleCatalog | None = None,
    *,
    adapters: tuple[AdapterId, ...] = (AdapterId.CODEX,),
) -> str:
    return render_ruleset(project_ruleset(selection, catalog, adapters=adapters))
