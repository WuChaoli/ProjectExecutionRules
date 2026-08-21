from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources.abc import Traversable
from pathlib import Path

from jinja2 import BaseLoader, Environment, StrictUndefined, TemplateNotFound

from project_execution_rules.adapters.base import AdapterDetection, CommandRunner
from project_execution_rules.catalog import resource_root
from project_execution_rules.detection import ProjectFacts
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.frontmatter import parse_frontmatter
from project_execution_rules.initialize import ProjectSelection
from project_execution_rules.managed import (
    build_managed_install_plan,
    has_reparse_ancestor,
    is_reparse_point,
)
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
            adapter_home=paths.claude_home,
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
        from project_execution_rules.initialize import (
            project_change_required,
            validate_user_install,
        )
        from project_execution_rules.rendering import render_python_project_extension

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
        if verify_user_install:
            validate_user_install(self.id, selection, paths)
        changes: list[Change] = []
        project_claude_home = resolved / ".claude"
        if is_reparse_point(project_claude_home) or (
            project_claude_home.exists() and not project_claude_home.is_dir()
        ):
            raise ProjectRulesError(
                "PROJECT_OWNERSHIP_CONFLICT",
                f"Claude project directory is unsafe: {project_claude_home}",
                evidence={"target": str(project_claude_home)},
            )
        guide = project_claude_home / "CLAUDE.md"
        if (
            is_reparse_point(guide)
            and not guide.is_symlink()
            or guide.exists()
            and not (guide.is_file() or guide.is_symlink())
        ):
            raise ProjectRulesError(
                "PROJECT_OWNERSHIP_CONFLICT",
                f"Claude project guide target is unsafe: {guide}",
                evidence={"target": str(guide)},
            )
        if not guide.exists() and not guide.is_symlink():
            changes.append(
                Change(
                    action="write",
                    target=guide,
                    content=_templates().get_template("CLAUDE.md.j2").render().encode(),
                )
            )
        for domain in selection.override_domains:
            if domain != "python":
                raise ProjectRulesError(
                    "OVERRIDE_UNSUPPORTED",
                    f"no real Claude Project Rule Extension renderer exists for {domain}",
                )
            content = render_python_project_extension(facts)
            if content:
                rules_dir = project_claude_home / "rules"
                if has_reparse_ancestor(rules_dir, root=resolved):
                    raise ProjectRulesError(
                        "PROJECT_OWNERSHIP_CONFLICT",
                        f"Claude project rules directory is unsafe: {rules_dir}",
                        evidence={"target": str(rules_dir)},
                    )
                target = rules_dir / f"{domain}.project.md"
                if is_reparse_point(target) or (target.exists() and not target.is_file()):
                    raise ProjectRulesError(
                        "PROJECT_OWNERSHIP_CONFLICT",
                        f"Claude Project Rule Extension target is unsafe: {target}",
                        evidence={"target": str(target)},
                    )
                if not target.exists():
                    changes.append(
                        Change(
                            action="write",
                            target=target,
                            content=content.encode(),
                        )
                    )
        return ChangePlan(
            scope="project:claude",
            changes=tuple(change for change in changes if project_change_required(change)),
        )

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
            source_path = root.joinpath("rules", definition.file)
            source = _read_resource(source_path, "Rule", rule_id)
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
            source_path = root.joinpath(definition.file)
            source = _read_resource(source_path, "Skill", skill_id)
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
                        disable_model_invocation=(definition.invocation is SkillInvocation.USER),
                        body=body,
                    )
                    .encode(),
                )
            )
            resource_kind[target] = "skill"

        for agent_id in selection.agents:
            definition = catalog.agents[agent_id]
            source_path = root.joinpath(definition.file)
            body = _read_resource(source_path, "Agent", agent_id)
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


def _read_resource(path: Traversable, kind: str, resource_id: str) -> str:
    if not path.is_file():
        raise ProjectRulesError(
            f"{kind.upper()}_RESOURCE_MISSING",
            f"{kind} resource is missing: {resource_id}",
            evidence={"id": resource_id, "path": str(path)},
        )
    return path.read_text(encoding="utf-8")


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
