from __future__ import annotations

import re
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any

import yaml

from project_execution_rules.frontmatter import parse_frontmatter
from project_execution_rules.models import (
    ActivationType,
    CheckIssue,
    RuleCatalog,
    RuleDefinition,
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


def _as_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("catalog sequence fields must contain strings")
    return tuple(value)


def load_builtin_catalog() -> RuleCatalog:
    raw = yaml.safe_load(resource_root().joinpath("catalog.yaml").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("catalog must be a mapping")
    raw_rules = raw.get("rules")
    raw_profiles = raw.get("profiles")
    if not isinstance(raw_rules, dict) or not isinstance(raw_profiles, dict):
        raise ValueError("catalog requires rules and profiles mappings")
    rules: dict[str, RuleDefinition] = {}
    for domain, value in raw_rules.items():
        if not isinstance(domain, str) or not isinstance(value, dict):
            raise ValueError("catalog rule entries are invalid")
        rules[domain] = RuleDefinition(
            domain=domain,
            file=str(value["file"]),
            activation=ActivationType(str(value["activation"])),
            paths=_as_tuple(value.get("paths")),
            tasks=_as_tuple(value.get("tasks")),
            commands=_as_tuple(value.get("commands")),
            core=bool(value.get("core", True)),
            required=bool(value.get("required", False)),
        )
    profiles = {name: _as_tuple(domains) for name, domains in raw_profiles.items()}
    return RuleCatalog(
        schema_version=int(raw["schema_version"]),
        rules_version=str(raw["rules_version"]),
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
        frontmatter_paths = tuple(metadata.get("paths", ()))
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
