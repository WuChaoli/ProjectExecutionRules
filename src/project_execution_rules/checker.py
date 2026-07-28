from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Collection
from pathlib import Path

from project_execution_rules.catalog import (
    load_builtin_catalog,
    validate_catalog_resources,
)
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.frontmatter import parse_frontmatter
from project_execution_rules.initialize import expected_manifest_entries
from project_execution_rules.managed import (
    ManagedManifest,
    is_safe_adapter_file,
    sha256_bytes,
)
from project_execution_rules.models import (
    ActivationType,
    AdapterId,
    CheckIssue,
    CheckReport,
    ProjectState,
    RuleCatalog,
    RuleSet,
    SkillInvocation,
)
from project_execution_rules.paths import UserPaths
from project_execution_rules.rendering import route_row
from project_execution_rules.rulesets import load_ruleset
from project_execution_rules.selection import CatalogSelection, resolve_catalog_selection
from project_execution_rules.yaml_utils import (
    as_mapping,
    as_object_tuple,
    as_string,
    as_string_tuple,
)

LinkVerifier = Callable[[Path, Path], bool]
_OVERRIDE_ID = re.compile(r"`([A-Z][A-Z0-9]*-OVR-\d{3})`")
_BASE_ID = re.compile(r"`([A-Z][A-Z0-9]*-\d{3})`")
_EXTENSION_NAME = re.compile(r"(?P<domain>[a-z0-9]+(?:-[a-z0-9]+)*)\.project\.md\Z")


def _actual_link_verifier(link: Path, target: Path) -> bool:
    return link.is_symlink() and link.resolve() == target.resolve()


def _git_tracked_files(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return set()
    return {line.replace("\\", "/") for line in result.stdout.splitlines()}


def _issue(
    code: str,
    message: str,
    *,
    severity: str = "error",
    **evidence: object,
) -> CheckIssue:
    return CheckIssue(code=code, message=message, severity=severity, evidence=dict(evidence))


def _adapter_issue(
    adapter: AdapterId,
    code: str,
    message: str,
    *,
    severity: str = "error",
    **evidence: object,
) -> CheckIssue:
    return _issue(
        code,
        message,
        severity=severity,
        adapter=adapter.value,
        **evidence,
    )


def _adapter_home(adapter: AdapterId, paths: UserPaths) -> Path:
    return paths.home if adapter is AdapterId.CODEX else paths.claude_home


def _managed_user_issues(
    adapter: AdapterId,
    paths: UserPaths,
    catalog: RuleCatalog,
    required: CatalogSelection,
) -> tuple[list[CheckIssue], ManagedManifest | None]:
    manifest_path = paths.manifest_path(adapter)
    if not manifest_path.is_file():
        return [
            _adapter_issue(
                adapter,
                "MANAGED_MANIFEST_MISSING",
                f"{adapter.value} user resource manifest is missing",
                manifest=str(manifest_path),
            )
        ], None
    try:
        manifest = ManagedManifest.load(manifest_path, expected_adapter=adapter)
    except (OSError, ValueError, TypeError, KeyError, ProjectRulesError) as error:
        return [
            _adapter_issue(
                adapter,
                "MANAGED_MANIFEST_INVALID",
                f"{adapter.value} user resource manifest is invalid: {error}",
                manifest=str(manifest_path),
            )
        ], None

    issues: list[CheckIssue] = []
    selected = manifest.selection
    try:
        closure = resolve_catalog_selection(catalog, selected.rules, adapter=adapter)
    except ValueError as error:
        issues.append(
            _adapter_issue(
                adapter,
                "MANAGED_SELECTION_INVALID",
                f"{adapter.value} manifest selection is not a Catalog closure",
                error=str(error),
            )
        )
        closure = CatalogSelection((), (), ())

    expected_selection = (set(closure.rules), set(closure.skills), set(closure.agents))
    actual_selection = (set(selected.rules), set(selected.skills), set(selected.agents))
    expected_entries = expected_manifest_entries(adapter, closure)
    actual_entries = {entry.logical_path: entry.kind for entry in manifest.entries}
    if expected_selection != actual_selection or expected_entries != actual_entries:
        issues.append(
            _adapter_issue(
                adapter,
                "MANAGED_SELECTION_INVALID",
                f"{adapter.value} manifest is not the exact selected closure",
            )
        )
    if manifest.resource_version != catalog.rules_version:
        issues.append(
            _adapter_issue(
                adapter,
                "MANAGED_RESOURCE_VERSION_MISMATCH",
                f"{adapter.value} resources do not match the Catalog version",
                installed=manifest.resource_version,
                required=catalog.rules_version,
            )
        )
    if not (
        set(required.rules) <= set(selected.rules)
        and set(required.skills) <= set(selected.skills)
        and set(required.agents) <= set(selected.agents)
    ):
        issues.append(
            _adapter_issue(
                adapter,
                "MANAGED_DEPENDENCY_MISSING",
                f"{adapter.value} user resources do not cover the project selection",
            )
        )

    adapter_home = _adapter_home(adapter, paths)
    for entry in manifest.entries:
        target = adapter_home / entry.logical_path
        if not is_safe_adapter_file(target, adapter_home=adapter_home):
            issues.append(
                _adapter_issue(
                    adapter,
                    "MANAGED_RESOURCE_DRIFTED",
                    f"managed user resource is missing or modified: {entry.logical_path}",
                    target=str(target),
                )
            )
            continue
        if adapter is AdapterId.CLAUDE:
            issues.extend(_claude_global_shape_issues(entry.logical_path, target, catalog))
        if sha256_bytes(target.read_bytes()) != entry.sha256:
            issues.append(
                _adapter_issue(
                    adapter,
                    "MANAGED_RESOURCE_DRIFTED",
                    f"managed user resource is missing or modified: {entry.logical_path}",
                    target=str(target),
                )
            )
    return issues, manifest


def _claude_global_shape_issues(
    logical_path: str, target: Path, catalog: RuleCatalog
) -> list[CheckIssue]:
    adapter = AdapterId.CLAUDE
    try:
        metadata, _ = parse_frontmatter(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        kind = "RULE"
        if logical_path.startswith("skills/"):
            kind = "SKILL"
        elif logical_path.startswith("agents/"):
            kind = "AGENT"
        return [
            _adapter_issue(
                adapter,
                f"CLAUDE_{kind}_FRONTMATTER_INVALID",
                f"Claude {kind.title()} frontmatter is invalid: {logical_path}",
                target=str(target),
                error=str(error),
            )
        ]

    if logical_path.startswith("rules/"):
        rule_id = target.stem
        definition = catalog.rules.get(rule_id)
        expected = definition.paths if definition is not None else ()
        try:
            actual = as_string_tuple(metadata.get("paths", ()), name="Claude Rule paths")
        except ValueError as error:
            return [
                _adapter_issue(
                    adapter,
                    "CLAUDE_RULE_FRONTMATTER_INVALID",
                    f"Claude Rule frontmatter is invalid: {logical_path}",
                    target=str(target),
                    error=str(error),
                )
            ]
        if actual != expected or (
            definition is not None
            and definition.activation is not ActivationType.PATHS
            and metadata
        ):
            return [
                _adapter_issue(
                    adapter,
                    "CLAUDE_RULE_FRONTMATTER_INVALID",
                    f"Claude Rule frontmatter differs from the Catalog: {logical_path}",
                    target=str(target),
                )
            ]
        return []

    if logical_path.startswith("skills/"):
        skill_id = target.parent.name
        definition = catalog.skills.get(skill_id)
        try:
            name = as_string(metadata["name"], name="Claude Skill name")
            description = as_string(metadata["description"], name="Claude Skill description")
            disabled = metadata.get("disable-model-invocation", False)
            if name != skill_id or not description:
                raise ValueError("Skill name and description must identify the resource")
            if type(disabled) is not bool:
                raise ValueError("disable-model-invocation must be a boolean")
            expected_disabled = (
                definition is not None and definition.invocation is SkillInvocation.USER
            )
            if disabled is not expected_disabled:
                raise ValueError("disable-model-invocation differs from the Catalog")
        except (OSError, UnicodeError, KeyError, TypeError, ValueError) as error:
            return [
                _adapter_issue(
                    adapter,
                    "CLAUDE_SKILL_FRONTMATTER_INVALID",
                    f"Claude Skill frontmatter is invalid: {logical_path}",
                    target=str(target),
                    error=str(error),
                )
            ]
        return []

    agent_id = target.stem
    definition = catalog.agents.get(agent_id)
    try:
        name = as_string(metadata["name"], name="Claude Agent name")
        description = as_string(metadata["description"], name="Claude Agent description")
        skills = as_string_tuple(metadata["skills"], name="Claude Agent skills")
        if name != agent_id or not description:
            raise ValueError("Agent name and description must identify the resource")
    except (OSError, UnicodeError, KeyError, TypeError, ValueError) as error:
        return [
            _adapter_issue(
                adapter,
                "CLAUDE_AGENT_FRONTMATTER_INVALID",
                f"Claude Agent frontmatter is invalid: {logical_path}",
                target=str(target),
                error=str(error),
            )
        ]
    expected_skills = tuple(
        skill_id
        for skill_id in (() if definition is None else definition.skills)
        if catalog.skills[skill_id].invocation is SkillInvocation.MODEL
    )
    if skills != expected_skills:
        return [
            _adapter_issue(
                adapter,
                "CLAUDE_AGENT_SKILLS_INVALID",
                f"Claude Agent preloaded Skills differ from the Catalog: {logical_path}",
                target=str(target),
            )
        ]
    return []


def _claude_project_issues(
    root: Path,
    ruleset: RuleSet,
    manifest: ManagedManifest | None,
    catalog: RuleCatalog,
) -> list[CheckIssue]:
    adapter = AdapterId.CLAUDE
    issues: list[CheckIssue] = []
    guide = root / ".claude" / "CLAUDE.md"
    if not (guide.is_file() or guide.is_symlink()):
        issues.append(
            _adapter_issue(
                adapter,
                "CLAUDE_GUIDE_MISSING",
                "Claude project guide is missing",
                target=str(guide),
            )
        )

    rules_dir = root / ".claude" / "rules"
    expected_extensions = set(ruleset.overrides[adapter])
    seen_extensions: set[str] = set()
    if rules_dir.is_dir():
        for target in rules_dir.iterdir():
            match = _EXTENSION_NAME.fullmatch(target.name)
            if match is None:
                continue
            domain = match.group("domain")
            seen_extensions.add(domain)
            if not is_safe_adapter_file(target, adapter_home=root / ".claude"):
                issues.append(
                    _adapter_issue(
                        adapter,
                        "CLAUDE_EXTENSION_NOT_REGULAR",
                        f"Claude Project Rule Extension must be a regular file: {domain}",
                        target=str(target),
                    )
                )
                continue
            if domain not in ruleset.overrides[adapter] or domain not in ruleset.domains:
                issues.append(
                    _adapter_issue(
                        adapter,
                        "CLAUDE_EXTENSION_OUT_OF_SCOPE",
                        f"Claude Project Rule Extension is outside the selected scope: {domain}",
                        target=str(target),
                    )
                )
                continue
            try:
                metadata, _ = parse_frontmatter(target.read_text(encoding="utf-8"))
                extension_paths = set(
                    as_string_tuple(
                        metadata.get("paths", ()),
                        name=f"{domain} Project Rule Extension paths",
                    )
                )
            except (OSError, UnicodeError, ValueError) as error:
                issues.append(
                    _adapter_issue(
                        adapter,
                        "CLAUDE_EXTENSION_FRONTMATTER_INVALID",
                        f"Claude Project Rule Extension frontmatter is invalid: {domain}",
                        target=str(target),
                        error=str(error),
                    )
                )
                continue
            if extension_paths and not extension_paths <= set(catalog.rules[domain].paths):
                issues.append(
                    _adapter_issue(
                        adapter,
                        "CLAUDE_EXTENSION_TRIGGER_EXPANDED",
                        f"Claude Project Rule Extension expands the Base trigger: {domain}",
                        target=str(target),
                    )
                )
    for domain in sorted(expected_extensions - seen_extensions):
        issues.append(
            _adapter_issue(
                adapter,
                "CLAUDE_EXTENSION_MISSING",
                f"declared Claude Project Rule Extension is missing: {domain}",
                target=str(rules_dir / f"{domain}.project.md"),
            )
        )

    installed_skills = set(() if manifest is None else manifest.selection.skills)
    project_skills = root / ".claude" / "skills"
    seen_skill_ids: set[str] = set()
    if project_skills.is_dir():
        for skill_file in project_skills.rglob("SKILL.md"):
            skill_id = skill_file.parent.name
            if skill_id in seen_skill_ids:
                issues.append(
                    _adapter_issue(
                        adapter,
                        "CLAUDE_PROJECT_SKILL_DUPLICATE",
                        f"project Claude Skill ID is duplicated: {skill_id}",
                        target=str(skill_file),
                    )
                )
            seen_skill_ids.add(skill_id)
            issues.extend(
                _project_skill_shape_issues(skill_id, skill_file, adapter_home=root / ".claude")
            )
            if skill_id in installed_skills:
                issues.append(
                    _adapter_issue(
                        adapter,
                        "CLAUDE_SKILL_SHADOWED",
                        f"user Claude Skill shadows a project Skill: {skill_id}",
                        target=str(skill_file),
                    )
                )

    installed_agents = set(() if manifest is None else manifest.selection.agents)
    project_agents = root / ".claude" / "agents"
    seen_agent_ids: set[str] = set()
    if project_agents.is_dir():
        for agent_file in project_agents.rglob("*.md"):
            agent_id = agent_file.stem
            if agent_id in seen_agent_ids:
                issues.append(
                    _adapter_issue(
                        adapter,
                        "CLAUDE_PROJECT_AGENT_DUPLICATE",
                        f"project Claude Agent ID is duplicated: {agent_id}",
                        target=str(agent_file),
                    )
                )
            seen_agent_ids.add(agent_id)
            issues.extend(
                _project_agent_shape_issues(agent_id, agent_file, adapter_home=root / ".claude")
            )
            if agent_id in installed_agents:
                issues.append(
                    _adapter_issue(
                        adapter,
                        "CLAUDE_AGENT_REPLACED",
                        f"project Claude Agent replaces a user Agent: {agent_id}",
                        severity="warning",
                        target=str(agent_file),
                    )
                )
    return issues


def _project_skill_shape_issues(
    skill_id: str, target: Path, *, adapter_home: Path
) -> list[CheckIssue]:
    try:
        if not is_safe_adapter_file(target, adapter_home=adapter_home):
            raise ValueError("project Claude Skill must be a regular in-project file")
        metadata, _ = parse_frontmatter(target.read_text(encoding="utf-8"))
        name = as_string(metadata["name"], name="project Claude Skill name")
        description = as_string(metadata["description"], name="project Claude Skill description")
        if name != skill_id or not description:
            raise ValueError("Skill name and description must identify the directory")
    except (OSError, UnicodeError, KeyError, TypeError, ValueError) as error:
        return [
            _adapter_issue(
                AdapterId.CLAUDE,
                "CLAUDE_PROJECT_SKILL_INVALID",
                f"project Claude Skill is invalid: {skill_id}",
                target=str(target),
                error=str(error),
            )
        ]
    return []


def _project_agent_shape_issues(
    agent_id: str, target: Path, *, adapter_home: Path
) -> list[CheckIssue]:
    try:
        if not is_safe_adapter_file(target, adapter_home=adapter_home):
            raise ValueError("project Claude Agent must be a regular in-project file")
        metadata, _ = parse_frontmatter(target.read_text(encoding="utf-8"))
        name = as_string(metadata["name"], name="project Claude Agent name")
        description = as_string(metadata["description"], name="project Claude Agent description")
        as_string_tuple(metadata["skills"], name="project Claude Agent skills")
        if name != agent_id or not description:
            raise ValueError("Agent name and description must identify the file")
    except (OSError, UnicodeError, KeyError, TypeError, ValueError) as error:
        return [
            _adapter_issue(
                AdapterId.CLAUDE,
                "CLAUDE_PROJECT_AGENT_INVALID",
                f"project Claude Agent is invalid: {agent_id}",
                target=str(target),
                error=str(error),
            )
        ]
    return []


def _override_operation_issue(
    metadata: dict[str, object],
    body: str,
    *,
    domain: str,
    valid_base_ids: set[str],
    override_paths: set[str],
) -> CheckIssue | None:
    try:
        if metadata.get("override_schema") != 1:
            raise ValueError("override_schema must be 1")
        raw_operations = as_object_tuple(
            metadata["operations"], name=f"{domain} Override operations"
        )
        if not raw_operations:
            raise ValueError("operations must not be empty")
        declared_ids: set[str] = set()
        for raw_operation in raw_operations:
            operation = as_mapping(raw_operation, name=f"{domain} Override operation")
            rule_id = as_string(operation["id"], name="Override operation id")
            kind = as_string(operation["operation"], name="Override operation type")
            target = as_string(operation["target"], name="Override operation target")
            if not re.fullmatch(r"[A-Z][A-Z0-9]*-OVR-\d{3}", rule_id):
                raise ValueError(f"invalid Override operation id: {rule_id}")
            if rule_id in declared_ids:
                raise ValueError(f"duplicate Override operation id: {rule_id}")
            declared_ids.add(rule_id)
            if kind == "add_constraint":
                if target not in valid_base_ids:
                    raise ValueError(f"unknown Base Rule target: {target}")
            elif kind == "narrow_paths":
                if target != domain or not override_paths:
                    raise ValueError("narrow_paths must target its domain and declare paths")
            else:
                raise ValueError(f"unsupported Override operation: {kind}")
        body_ids = set(_OVERRIDE_ID.findall(body))
        if body_ids != declared_ids:
            raise ValueError("Override operation IDs must exactly match body Rule IDs")
    except (KeyError, TypeError, ValueError) as error:
        return _issue(
            "OVERRIDE_OPERATION_INVALID",
            f"Override operations are invalid: {domain}",
            error=str(error),
        )
    return None


def _codex_project_issues(
    root: Path,
    paths: UserPaths,
    ruleset: RuleSet,
    catalog: RuleCatalog,
    *,
    tracked: set[str],
    link_verifier: LinkVerifier,
) -> tuple[list[CheckIssue], int]:
    adapter = AdapterId.CODEX
    issues: list[CheckIssue] = []
    loaded_rule_bytes = 0
    for domain in ruleset.domains:
        link = root / ".rules" / f"{domain}-rules.md"
        target = paths.rules_home / f"{domain}-rules.md"
        if link.is_file():
            loaded_rule_bytes += len(link.read_bytes())
        if not link_verifier(link, target):
            issues.append(
                _adapter_issue(
                    adapter,
                    "BASE_LINK_INVALID",
                    f"Base Rule link is missing or targets the wrong file: {domain}",
                    link=str(link),
                    target=str(target),
                )
            )

    agents = root / "AGENTS.md"
    agents_text = agents.read_text(encoding="utf-8") if agents.is_file() else ""
    if len(agents_text.encode("utf-8")) > 8192:
        issues.append(_adapter_issue(adapter, "AGENTS_BUDGET_EXCEEDED", "AGENTS.md exceeds 8 KiB"))
    for domain in ruleset.domains:
        expected = route_row(domain, catalog.rules[domain])
        if expected not in agents_text:
            issues.append(
                _adapter_issue(
                    adapter, "AGENTS_ROUTE_MISSING", f"AGENTS.md does not route {domain}"
                )
            )

    seen_override_ids: set[str] = set()
    for domain in ruleset.overrides[adapter]:
        override = root / ".rules" / f"{domain}-rules.override.md"
        relative = override.relative_to(root).as_posix()
        if not override.is_file():
            issues.append(
                _adapter_issue(
                    adapter, "OVERRIDE_MISSING", f"declared Override is missing: {domain}"
                )
            )
            continue
        if override.is_symlink():
            issues.append(
                _adapter_issue(
                    adapter, "OVERRIDE_NOT_REGULAR", f"Override must be a regular file: {domain}"
                )
            )
        if relative not in tracked:
            issues.append(
                _adapter_issue(
                    adapter, "OVERRIDE_UNTRACKED", f"Override is not tracked by Git: {domain}"
                )
            )
        text = override.read_text(encoding="utf-8")
        loaded_rule_bytes += len(text.encode("utf-8"))
        if len(text.encode("utf-8")) > 4096:
            issues.append(
                _adapter_issue(
                    adapter, "OVERRIDE_BUDGET_EXCEEDED", f"Override exceeds 4 KiB: {domain}"
                )
            )
        try:
            metadata, body = parse_frontmatter(text)
        except ValueError as error:
            issues.append(
                _adapter_issue(
                    adapter,
                    "OVERRIDE_FRONTMATTER_INVALID",
                    f"Override frontmatter is invalid: {domain}",
                    error=str(error),
                )
            )
            continue
        base_paths = set(catalog.rules[domain].paths)
        try:
            override_paths = set(
                as_string_tuple(metadata.get("paths", ()), name=f"{domain} Override paths")
            )
        except ValueError as error:
            issues.append(
                _adapter_issue(
                    adapter,
                    "OVERRIDE_FRONTMATTER_INVALID",
                    f"Override frontmatter is invalid: {domain}",
                    error=str(error),
                )
            )
            continue
        if override_paths and not override_paths <= base_paths:
            issues.append(
                _adapter_issue(
                    adapter,
                    "OVERRIDE_TRIGGER_EXPANDED",
                    f"Override expands the Base trigger: {domain}",
                )
            )
        base = paths.rules_home / f"{domain}-rules.md"
        valid_base_ids: set[str] = set()
        if base.is_file():
            valid_base_ids.update(_BASE_ID.findall(base.read_text(encoding="utf-8")))
        operation_issue = _override_operation_issue(
            metadata,
            body,
            domain=domain,
            valid_base_ids=valid_base_ids,
            override_paths=override_paths,
        )
        if operation_issue is not None:
            issues.append(
                _adapter_issue(
                    adapter,
                    operation_issue.code,
                    operation_issue.message,
                    **operation_issue.evidence,
                )
            )
        for rule_id in _OVERRIDE_ID.findall(body):
            if rule_id in seen_override_ids:
                issues.append(
                    _adapter_issue(
                        adapter, "RULE_ID_DUPLICATE", f"Override Rule ID is duplicated: {rule_id}"
                    )
                )
            seen_override_ids.add(rule_id)
    return issues, loaded_rule_bytes


def check_project(
    root: Path,
    paths: UserPaths,
    *,
    tracked_files: Collection[str] | None = None,
    link_verifier: LinkVerifier = _actual_link_verifier,
) -> CheckReport:
    resolved = root.resolve()
    ruleset_path = resolved / ".rules" / "ruleset.yaml"
    if not ruleset_path.is_file():
        return CheckReport(
            state=ProjectState.UNMANAGED,
            issues=(
                _issue(
                    "RULESET_MISSING",
                    "project is not managed because .rules/ruleset.yaml is missing",
                ),
            ),
        )
    try:
        ruleset = load_ruleset(ruleset_path)
    except ProjectRulesError as error:
        return CheckReport(
            state=ProjectState.INCOMPATIBLE,
            issues=(_issue(error.code, error.message, **error.evidence),),
        )

    catalog = load_builtin_catalog()
    issues = list(validate_catalog_resources(catalog))
    try:
        required_by_adapter = {
            adapter: resolve_catalog_selection(catalog, ruleset.domains, adapter=adapter)
            for adapter in ruleset.adapters
        }
    except ValueError as error:
        return CheckReport(
            state=ProjectState.INCOMPATIBLE,
            issues=(_issue("CATALOG_SELECTION_INVALID", str(error)),),
        )

    manifests: dict[AdapterId, ManagedManifest | None] = {}
    for adapter in ruleset.adapters:
        adapter_issues, manifest = _managed_user_issues(
            adapter, paths, catalog, required_by_adapter[adapter]
        )
        issues.extend(adapter_issues)
        manifests[adapter] = manifest

    tracked = (
        {item.replace("\\", "/") for item in tracked_files}
        if tracked_files is not None
        else _git_tracked_files(resolved)
    )
    loaded_rule_bytes = 0
    if AdapterId.CODEX in ruleset.adapters:
        codex_issues, loaded_rule_bytes = _codex_project_issues(
            resolved,
            paths,
            ruleset,
            catalog,
            tracked=tracked,
            link_verifier=link_verifier,
        )
        issues.extend(codex_issues)
    if AdapterId.CLAUDE in ruleset.adapters:
        issues.extend(
            _claude_project_issues(resolved, ruleset, manifests[AdapterId.CLAUDE], catalog)
        )
    if loaded_rule_bytes > 24 * 1024:
        issues.append(
            _adapter_issue(
                AdapterId.CODEX,
                "LOADED_RULES_BUDGET_EXCEEDED",
                "selected Base and Override Rules exceed the 24 KiB cumulative budget",
                bytes=loaded_rule_bytes,
            )
        )

    version_state = (
        ProjectState.UPDATE_AVAILABLE
        if ruleset.rules_version != catalog.rules_version
        else ProjectState.HEALTHY
    )
    has_error = any(issue.severity == "error" for issue in issues)
    return CheckReport(
        state=ProjectState.DRIFTED if has_error else version_state,
        issues=tuple(issues),
    )
