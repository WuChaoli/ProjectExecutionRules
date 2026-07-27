from __future__ import annotations

from pathlib import Path

import yaml

from project_execution_rules.catalog import load_builtin_catalog
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.models import AdapterId, RuleSet
from project_execution_rules.yaml_utils import (
    as_int,
    as_mapping,
    as_string,
    as_string_tuple,
    load_mapping,
)

_SCHEMA_VERSION = 2
_TOP_LEVEL_KEYS = {
    "schema_version",
    "rules_version",
    "adapters",
    "profile",
    "domains",
    "overrides",
}
_DOMAIN_KEYS = {"core", "profile"}


def _invalid(message: str) -> ProjectRulesError:
    return ProjectRulesError("RULESET_INVALID", f"RULESET_INVALID: {message}")


def _incompatible(schema_version: object) -> ProjectRulesError:
    return ProjectRulesError(
        "RULESET_SCHEMA_INCOMPATIBLE",
        "RULESET_SCHEMA_INCOMPATIBLE: Rule Set schema is not supported",
        evidence={"schema_version": schema_version},
    )


def load_ruleset(path: Path) -> RuleSet:
    try:
        return load_ruleset_text(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise _invalid(str(error)) from error


def load_ruleset_text(text: str) -> RuleSet:
    try:
        raw = load_mapping(text, name="Rule Set")
        schema_version = as_int(raw.get("schema_version"), name="schema_version")
    except ValueError as error:
        raise _invalid(str(error)) from error
    if schema_version != _SCHEMA_VERSION:
        raise _incompatible(schema_version)

    unknown_keys = set(raw) - _TOP_LEVEL_KEYS
    if unknown_keys:
        raise _invalid(f"unknown keys: {', '.join(sorted(unknown_keys))}")

    try:
        adapter_values = as_string_tuple(raw.get("adapters"), name="Adapters")
        domains = as_mapping(raw.get("domains"), name="Rule Set domains")
        unknown_domain_keys = set(domains) - _DOMAIN_KEYS
        if unknown_domain_keys:
            raise ValueError(
                f"Rule Set domains contains unknown keys: {', '.join(sorted(unknown_domain_keys))}"
            )
        core_domains = as_string_tuple(domains.get("core"), name="Core domains")
        profile_domains = as_string_tuple(domains.get("profile"), name="Profile domains")
        overrides_raw = as_mapping(raw.get("overrides"), name="Rule Set overrides")
        rules_version = as_string(raw.get("rules_version"), name="rules_version")
        profile = as_string(raw.get("profile"), name="profile")
    except ValueError as error:
        raise _invalid(str(error)) from error

    if not adapter_values:
        raise _invalid("Adapters must be non-empty")
    if len(set(adapter_values)) != len(adapter_values):
        raise _invalid("Adapters must not contain duplicate values")
    try:
        adapters = tuple(AdapterId(value) for value in adapter_values)
    except ValueError as error:
        raise _incompatible(adapter_values) from error
    from project_execution_rules.adapters import registered_adapter_ids

    expected = tuple(adapter for adapter in registered_adapter_ids() if adapter in adapters)
    if adapters != expected:
        raise _invalid("Adapters must use Registry order")

    expected_override_keys = {adapter.value for adapter in adapters}
    if set(overrides_raw) != expected_override_keys:
        raise _invalid("Overrides must contain exactly the selected Adapter keys")
    selected_domains = set(core_domains + profile_domains)
    catalog = load_builtin_catalog()
    unknown_domains = selected_domains - set(catalog.rules)
    if unknown_domains:
        raise _invalid(f"unknown Rule domain: {', '.join(sorted(unknown_domains))}")
    if profile not in catalog.profiles:
        raise _invalid(f"unknown profile: {profile}")
    core_rule_ids = {
        domain for domain, definition in catalog.rules.items() if definition.core
    }
    if not set(core_domains) <= core_rule_ids:
        raise _invalid("domains.core must contain only Catalog core Rules")
    profile_rule_ids = set(catalog.profiles[profile])
    if not set(profile_domains) <= profile_rule_ids:
        raise _invalid(f"domains.profile must contain only Profile {profile} Rules")
    overrides: dict[AdapterId, tuple[str, ...]] = {}
    try:
        for adapter in adapters:
            adapter_overrides = as_string_tuple(
                overrides_raw[adapter.value],
                name=f"{adapter.value} Overrides",
            )
            if len(set(adapter_overrides)) != len(adapter_overrides):
                raise ValueError(f"{adapter.value} Overrides contain duplicate values")
            if not set(adapter_overrides) <= selected_domains:
                raise ValueError(
                    f"{adapter.value} Override must reference a selected domain"
                )
            overrides[adapter] = adapter_overrides
    except ValueError as error:
        raise _invalid(str(error)) from error

    if len(set(core_domains + profile_domains)) != len(core_domains + profile_domains):
        raise _invalid("Rule Set domains must not contain duplicate values")

    return RuleSet(
        schema_version=schema_version,
        rules_version=rules_version,
        adapters=adapters,
        profile=profile,
        core_domains=core_domains,
        profile_domains=profile_domains,
        overrides=overrides,
    )


def render_ruleset(ruleset: RuleSet) -> str:
    raw: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "rules_version": ruleset.rules_version,
        "adapters": [adapter.value for adapter in ruleset.adapters],
        "profile": ruleset.profile,
        "domains": {
            "core": list(ruleset.core_domains),
            "profile": list(ruleset.profile_domains),
        },
        "overrides": {
            adapter.value: list(ruleset.overrides.get(adapter, ()))
            for adapter in ruleset.adapters
        },
    }
    return yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)
