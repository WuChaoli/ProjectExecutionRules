from __future__ import annotations

import json
import re
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any

import jsonschema

from project_execution_rules.frontmatter import parse_frontmatter
from project_execution_rules.models import (
    ActivationType,
    AdapterId,
    AgentDefinition,
    CheckIssue,
    RuleCatalog,
    RuleDefinition,
    SkillDefinition,
    SkillInvocation,
)
from project_execution_rules.yaml_utils import (
    as_int,
    as_mapping,
    as_string,
    as_string_tuple,
    load_mapping,
)

_RULE_ID = re.compile(r"`([A-Z][A-Z0-9]*(?:-OVR)?-\d{3})`")
_RESOURCE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PREFIXES = {
    "security": "SEC",
    "testing": "TST",
    "documentation": "DOC",
    "git": "GIT",
    "pull-request": "PR",
    "ci-cd": "CICD",
    "debug": "DBG",
    "observability": "OBS",
    "architecture": "ARC",
    "external-services": "EXT",
    "agent": "AGT",
    "tool": "TOL",
    "harness": "HAR",
    "python": "PY",
}


def resource_root() -> Traversable:
    return files("project_execution_rules").joinpath("resources")


def _validate_catalog_schema(raw: dict[str, object]) -> None:
    schema_text = resource_root().joinpath("schemas/catalog.schema.json").read_text(
        encoding="utf-8"
    )
    schema = as_mapping(json.loads(schema_text), name="Catalog schema")
    try:
        jsonschema.validate(raw, schema)
    except jsonschema.ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path)
        prefix = f" at {location}" if location else ""
        raise ValueError(f"Catalog schema invalid{prefix}: {error.message}") from error


def load_builtin_catalog() -> RuleCatalog:
    raw = load_mapping(
        resource_root().joinpath("catalog.yaml").read_text(encoding="utf-8"),
        name="Catalog",
    )
    _validate_catalog_schema(raw)
    raw_rules = as_mapping(raw.get("rules"), name="Catalog rules")
    raw_profiles = as_mapping(raw.get("profiles"), name="Catalog profiles")
    raw_skills = as_mapping(raw.get("skills"), name="Catalog skills")
    raw_agents = as_mapping(raw.get("agents"), name="Catalog agents")
    rules: dict[str, RuleDefinition] = {}
    for domain, value in raw_rules.items():
        rule = as_mapping(value, name=f"Catalog rule {domain}")
        rules[domain] = RuleDefinition(
            domain=domain,
            file=as_string(rule["file"], name=f"{domain} file"),
            activation=ActivationType(as_string(rule["activation"], name=f"{domain} activation")),
            paths=as_string_tuple(rule.get("paths", ()), name=f"{domain} paths"),
            tasks=as_string_tuple(rule.get("tasks", ()), name=f"{domain} tasks"),
            commands=as_string_tuple(rule.get("commands", ()), name=f"{domain} commands"),
            skills=as_string_tuple(rule.get("skills", ()), name=f"{domain} skills"),
            agents=as_string_tuple(rule.get("agents", ()), name=f"{domain} agents"),
            core=bool(rule.get("core", True)),
            required=bool(rule.get("required", False)),
        )
    profiles = {
        name: as_string_tuple(domains, name=f"Profile {name}")
        for name, domains in raw_profiles.items()
    }
    skills: dict[str, SkillDefinition] = {}
    for skill_id, value in raw_skills.items():
        skill = as_mapping(value, name=f"Catalog Skill {skill_id}")
        skills[skill_id] = SkillDefinition(
            skill_id=skill_id,
            file=as_string(skill["file"], name=f"{skill_id} file"),
            invocation=SkillInvocation(
                as_string(skill["invocation"], name=f"{skill_id} invocation")
            ),
            adapters=tuple(
                AdapterId(adapter)
                for adapter in as_string_tuple(
                    skill.get("adapters", ()), name=f"{skill_id} adapters"
                )
            ),
        )
    agents: dict[str, AgentDefinition] = {}
    for agent_id, value in raw_agents.items():
        agent = as_mapping(value, name=f"Catalog Agent {agent_id}")
        agents[agent_id] = AgentDefinition(
            agent_id=agent_id,
            file=as_string(agent["file"], name=f"{agent_id} file"),
            skills=as_string_tuple(agent.get("skills", ()), name=f"{agent_id} skills"),
            adapters=tuple(
                AdapterId(adapter)
                for adapter in as_string_tuple(
                    agent.get("adapters", ()), name=f"{agent_id} adapters"
                )
            ),
        )
    return RuleCatalog(
        schema_version=as_int(raw["schema_version"], name="schema_version"),
        rules_version=as_string(raw["rules_version"], name="rules_version"),
        rules=rules,
        profiles=profiles,
        skills=skills,
        agents=agents,
    )


def _issue(code: str, message: str, **evidence: Any) -> CheckIssue:
    return CheckIssue(code=code, message=message, evidence=evidence)


def _validate_catalog_structure(catalog: RuleCatalog) -> list[CheckIssue]:
    issues: list[CheckIssue] = []

    for domain, definition in catalog.rules.items():
        if not _RESOURCE_ID.fullmatch(domain):
            issues.append(_issue("RULE_ID_INVALID", f"invalid Rule ID: {domain}"))
        for skill_id in definition.skills:
            if skill_id not in catalog.skills:
                issues.append(
                    _issue(
                        "RULE_SKILL_MISSING",
                        f"Rule {domain} references missing Skill {skill_id}",
                    )
                )
        for agent_id in definition.agents:
            if agent_id not in catalog.agents:
                issues.append(
                    _issue(
                        "RULE_AGENT_MISSING",
                        f"Rule {domain} references missing Agent {agent_id}",
                    )
                )

        dependencies = [
            catalog.skills[skill_id].adapters
            for skill_id in definition.skills
            if skill_id in catalog.skills
        ] + [
            catalog.agents[agent_id].adapters
            for agent_id in definition.agents
            if agent_id in catalog.agents
        ]
        supported_adapters: set[AdapterId] | None = None
        for adapters in dependencies:
            if supported_adapters is None:
                supported_adapters = set(adapters)
            else:
                supported_adapters.intersection_update(adapters)
        if dependencies and not supported_adapters:
            issues.append(
                _issue(
                    "RULE_ADAPTER_UNAVAILABLE",
                    f"Rule {domain} dependencies share no supported Adapter",
                )
            )

    for skill_id, definition in catalog.skills.items():
        if not _RESOURCE_ID.fullmatch(skill_id) or definition.skill_id != skill_id:
            issues.append(_issue("SKILL_ID_INVALID", f"invalid Skill ID: {skill_id}"))
        if not definition.adapters:
            issues.append(
                _issue("SKILL_ADAPTERS_EMPTY", f"Skill {skill_id} supports no Adapter")
            )

    for agent_id, definition in catalog.agents.items():
        if not _RESOURCE_ID.fullmatch(agent_id) or definition.agent_id != agent_id:
            issues.append(_issue("AGENT_ID_INVALID", f"invalid Agent ID: {agent_id}"))
        if not definition.adapters:
            issues.append(
                _issue("AGENT_ADAPTERS_EMPTY", f"Agent {agent_id} supports no Adapter")
            )
        for skill_id in definition.skills:
            skill = catalog.skills.get(skill_id)
            if skill is None:
                issues.append(
                    _issue(
                        "AGENT_SKILL_MISSING",
                        f"Agent {agent_id} references missing Skill {skill_id}",
                    )
                )
                continue
            if skill_id == agent_id:
                issues.append(
                    _issue(
                        "AGENT_SKILL_SELF_REFERENCE",
                        f"Agent {agent_id} must not preload itself as a Skill",
                    )
                )
            if skill.invocation is SkillInvocation.USER:
                issues.append(
                    _issue(
                        "AGENT_SKILL_INVOCATION_INVALID",
                        f"Agent {agent_id} cannot preload user-only Skill {skill_id}",
                    )
                )
            unavailable = set(definition.adapters) - set(skill.adapters)
            if unavailable:
                issues.append(
                    _issue(
                        "AGENT_SKILL_ADAPTER_UNAVAILABLE",
                        f"Skill {skill_id} is unavailable for an Agent {agent_id} Adapter",
                        adapters=sorted(adapter.value for adapter in unavailable),
                    )
                )

    for profile, domains in catalog.profiles.items():
        if not _RESOURCE_ID.fullmatch(profile):
            issues.append(_issue("PROFILE_ID_INVALID", f"invalid Profile ID: {profile}"))
        for domain in domains:
            if domain not in catalog.rules:
                issues.append(
                    _issue(
                        "PROFILE_RULE_MISSING",
                        f"Profile {profile} references missing Rule {domain}",
                    )
                )
    return issues


def _is_safe_resource_file(file: str) -> bool:
    normalized = file.replace("\\", "/")
    parts = normalized.split("/")
    return bool(normalized) and not normalized.startswith("/") and ".." not in parts and not (
        len(normalized) >= 2 and normalized[1] == ":"
    )


def validate_catalog_resources(catalog: RuleCatalog) -> tuple[CheckIssue, ...]:
    issues = _validate_catalog_structure(catalog)
    resource_files = [
        ("SKILL_FILE", skill_id, definition.file)
        for skill_id, definition in catalog.skills.items()
    ] + [
        ("AGENT_FILE", agent_id, definition.file)
        for agent_id, definition in catalog.agents.items()
    ]
    resources = resource_root()
    for prefix, resource_id, file in resource_files:
        if not _is_safe_resource_file(file):
            issues.append(
                _issue(f"{prefix}_INVALID", f"invalid resource file for {resource_id}: {file}")
            )
        elif not resources.joinpath(file).is_file():
            issues.append(
                _issue(f"{prefix}_MISSING", f"missing resource file for {resource_id}")
            )
    seen_ids: dict[str, str] = {}
    always_bytes = 0
    root = resource_root().joinpath("rules")
    for domain, definition in catalog.rules.items():
        target = root.joinpath(definition.file)
        if not target.is_file():
            issues.append(_issue("RULE_FILE_MISSING", f"missing Rule file for {domain}"))
            continue
        text = target.read_text(encoding="utf-8")
        byte_count = len(text.encode("utf-8"))
        if byte_count > 8192:
            issues.append(
                _issue("RULE_BUDGET_EXCEEDED", f"{domain} exceeds 8192 bytes", bytes=byte_count)
            )
        if definition.activation is ActivationType.ALWAYS:
            always_bytes += byte_count
        try:
            metadata, body = parse_frontmatter(text)
        except ValueError as error:
            issues.append(_issue("RULE_FRONTMATTER_INVALID", str(error), domain=domain))
            continue
        frontmatter_paths = as_string_tuple(
            metadata.get("paths", ()), name=f"{domain} frontmatter paths"
        )
        if frontmatter_paths != definition.paths:
            issues.append(
                _issue(
                    "RULE_TRIGGER_DRIFT",
                    f"{domain} Catalog paths differ from frontmatter",
                    catalog=list(definition.paths),
                    frontmatter=list(frontmatter_paths),
                )
            )
        if definition.activation in {ActivationType.TASK, ActivationType.EXPLICIT} and metadata:
            issues.append(
                _issue(
                    "RULE_TRIGGER_INVALID",
                    f"{domain} task/explicit Rule must not have frontmatter",
                )
            )
        expected_prefix = _PREFIXES.get(domain)
        for rule_id in _RULE_ID.findall(body):
            if expected_prefix is not None and not rule_id.startswith(f"{expected_prefix}-"):
                issues.append(
                    _issue("RULE_ID_PREFIX", f"{rule_id} has wrong prefix", domain=domain)
                )
            previous = seen_ids.get(rule_id)
            if previous is not None:
                issues.append(
                    _issue(
                        "RULE_ID_DUPLICATE", f"{rule_id} is duplicated", files=[previous, domain]
                    )
                )
            seen_ids[rule_id] = domain
    if always_bytes > 24 * 1024:
        issues.append(
            _issue("STARTUP_BUDGET_EXCEEDED", "always Rules exceed 24 KiB", bytes=always_bytes)
        )
    return tuple(issues)
