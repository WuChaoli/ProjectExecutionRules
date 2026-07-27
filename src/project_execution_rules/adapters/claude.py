from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jinja2 import BaseLoader, Environment, StrictUndefined, TemplateNotFound

from project_execution_rules.adapters.base import AdapterDetection, CommandRunner
from project_execution_rules.catalog import resource_root
from project_execution_rules.detection import ProjectFacts
from project_execution_rules.frontmatter import parse_frontmatter
from project_execution_rules.initialize import ProjectSelection
from project_execution_rules.managed import build_managed_install_plan
from project_execution_rules.models import (
    AdapterId,
    Change,
    ChangePlan,
    RuleCatalog,
    SkillInvocation,
)
from project_execution_rules.paths import UserPaths
from project_execution_rules.selection import CatalogSelection


@dataclass(frozen=True, slots=True)
class ClaudeAdapter:
    @property
    def id(self) -> AdapterId:
        return AdapterId.CLAUDE

    def detect(self, runner: CommandRunner) -> AdapterDetection:
        result = runner(("claude", "--version"))
        return AdapterDetection(self.id, "claude", result.returncode == 0)

    def plan_install(
        self,
        paths: UserPaths,
        catalog: RuleCatalog,
        selection: CatalogSelection,
        *,
        allow_managed_drift: bool = False,
    ) -> ChangePlan:
        changes, resource_kind = self._resource_changes(paths, catalog, selection)
        return build_managed_install_plan(
            adapter=self.id,
            paths=paths,
            resource_version=catalog.rules_version,
            selection=selection,
            changes=changes,
            resource_kind=resource_kind,
            scope="user:claude",
            allow_managed_drift=allow_managed_drift,
        )

    def plan_project_init(
        self,
        root: Path,
        facts: ProjectFacts,
        selection: ProjectSelection,
        paths: UserPaths,
        *,
        verify_user_install: bool = True,
    ) -> ChangePlan:
        return ChangePlan(scope="project:claude", changes=())

    def _resource_changes(
        self,
        paths: UserPaths,
        catalog: RuleCatalog,
        selection: CatalogSelection,
    ) -> tuple[tuple[Change, ...], dict[Path, str]]:
        templates = _templates()
        root = resource_root()
        changes: list[Change] = []
        resource_kind: dict[Path, str] = {}

        for rule_id in selection.rules:
            definition = catalog.rules[rule_id]
            source = root.joinpath("rules", definition.file).read_text(encoding="utf-8")
            _, body = parse_frontmatter(source)
            target = paths.claude_rules / f"{rule_id}.md"
            changes.append(
                Change(
                    action="write",
                    target=target,
                    content=templates.get_template("rule.md.j2")
                    .render(paths=definition.paths, body=body)
                    .encode(),
                )
            )
            resource_kind[target] = "rule"

        for skill_id in selection.skills:
            definition = catalog.skills[skill_id]
            source = root.joinpath(definition.file).read_text(encoding="utf-8")
            metadata, body = parse_frontmatter(source)
            description = str(metadata.get("description", f"Apply the {skill_id} Skill."))
            target = paths.claude_skills / skill_id / "SKILL.md"
            changes.append(
                Change(
                    action="write",
                    target=target,
                    content=templates.get_template("skill.md.j2")
                    .render(
                        name=skill_id,
                        description=description,
                        disable_model_invocation=(
                            definition.invocation is SkillInvocation.USER
                        ),
                        body=body,
                    )
                    .encode(),
                )
            )
            resource_kind[target] = "skill"

        for agent_id in selection.agents:
            definition = catalog.agents[agent_id]
            body = root.joinpath(definition.file).read_text(encoding="utf-8")
            skills = [
                skill_id
                for skill_id in definition.skills
                if catalog.skills[skill_id].invocation is SkillInvocation.MODEL
            ]
            target = paths.claude_agents / f"{agent_id}.md"
            changes.append(
                Change(
                    action="write",
                    target=target,
                    content=templates.get_template("agent.md.j2")
                    .render(
                        name=agent_id,
                        description=f"Execute the {agent_id} Agent contract.",
                        skills=skills,
                        body=body,
                    )
                    .encode(),
                )
            )
            resource_kind[target] = "agent"

        return tuple(changes), resource_kind


class _ResourceTemplateLoader(BaseLoader):
    def get_source(
        self,
        environment: Environment,
        template: str,
    ) -> tuple[str, str, Callable[[], bool]]:
        resource = resource_root().joinpath("adapters", "claude", "templates", template)
        if not resource.is_file():
            raise TemplateNotFound(template)
        return resource.read_text(encoding="utf-8"), template, lambda: True


def _templates() -> Environment:
    return Environment(
        loader=_ResourceTemplateLoader(),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
