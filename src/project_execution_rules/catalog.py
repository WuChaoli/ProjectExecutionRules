from __future__ import annotations

import re
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any

from project_execution_rules.frontmatter import parse_frontmatter
from project_execution_rules.models import (
    ActivationType,
    CheckIssue,
    RuleCatalog,
    RuleDefinition,
)
from project_execution_rules.yaml_utils import (
    as_int,
    as_mapping,
    as_string,
    as_string_tuple,
    load_mapping,
)

_RULE_ID = re.compile(r"`([A-Z][A-Z0-9]*(?:-OVR)?-\d{3})`")
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


def load_builtin_catalog() -> RuleCatalog:
    raw = load_mapping(
        resource_root().joinpath("catalog.yaml").read_text(encoding="utf-8"),
        name="Catalog",
    )
    raw_rules = as_mapping(raw.get("rules"), name="Catalog rules")
    raw_profiles = as_mapping(raw.get("profiles"), name="Catalog profiles")
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
            core=bool(rule.get("core", True)),
            required=bool(rule.get("required", False)),
        )
    profiles = {
        name: as_string_tuple(domains, name=f"Profile {name}")
        for name, domains in raw_profiles.items()
    }
    return RuleCatalog(
        schema_version=as_int(raw["schema_version"], name="schema_version"),
        rules_version=as_string(raw["rules_version"], name="rules_version"),
        rules=rules,
        profiles=profiles,
    )


def _issue(code: str, message: str, **evidence: Any) -> CheckIssue:
    return CheckIssue(code=code, message=message, evidence=evidence)


def validate_catalog_resources(catalog: RuleCatalog) -> tuple[CheckIssue, ...]:
    issues: list[CheckIssue] = []
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
        expected_prefix = _PREFIXES[domain]
        for rule_id in _RULE_ID.findall(body):
            if not rule_id.startswith(f"{expected_prefix}-"):
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
