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
from project_execution_rules.managed import ManagedManifest, sha256_bytes
from project_execution_rules.models import AdapterId, CheckIssue, CheckReport, ProjectState
from project_execution_rules.paths import UserPaths
from project_execution_rules.rendering import route_row
from project_execution_rules.yaml_utils import (
    as_mapping,
    as_object_tuple,
    as_string,
    as_string_tuple,
    load_mapping,
)

LinkVerifier = Callable[[Path, Path], bool]
_OVERRIDE_ID = re.compile(r"`([A-Z][A-Z0-9]*-OVR-\d{3})`")
_BASE_ID = re.compile(r"`([A-Z][A-Z0-9]*-\d{3})`")


def _actual_link_verifier(link: Path, target: Path) -> bool:
    return link.is_symlink() and link.resolve() == target.resolve()


def _git_tracked_files(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {line.replace("\\", "/") for line in result.stdout.splitlines()}


def _issue(code: str, message: str, **evidence: object) -> CheckIssue:
    return CheckIssue(code=code, message=message, evidence=dict(evidence))


def _managed_user_issues(paths: UserPaths) -> list[CheckIssue]:
    manifest_path = paths.manifest_path(AdapterId.CODEX)
    if not manifest_path.is_file():
        return [_issue("MANAGED_MANIFEST_MISSING", "user resource manifest is missing")]
    try:
        manifest = ManagedManifest.load(
            manifest_path,
            expected_adapter=AdapterId.CODEX,
        )
    except (OSError, ValueError, TypeError, KeyError, ProjectRulesError) as error:
        return [_issue("MANAGED_MANIFEST_INVALID", f"user resource manifest is invalid: {error}")]
    issues: list[CheckIssue] = []
    for entry in manifest.entries:
        target = paths.home / entry.logical_path
        try:
            target.absolute().relative_to(paths.home.resolve())
            target.parent.resolve(strict=False).relative_to(paths.home.resolve())
        except ValueError:
            issues.append(
                _issue(
                    "MANAGED_RESOURCE_PATH_INVALID",
                    f"managed resource path escapes the user home: {entry.logical_path}",
                )
            )
            continue
        if (
            target.is_symlink()
            or not target.is_file()
            or sha256_bytes(target.read_bytes()) != entry.sha256
        ):
            issues.append(
                _issue(
                    "MANAGED_RESOURCE_DRIFTED",
                    f"managed user resource is missing or modified: {entry.logical_path}",
                    target=str(target),
                )
            )
    return issues


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
            metadata["operations"],
            name=f"{domain} Override operations",
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
    issues = list(validate_catalog_resources(load_builtin_catalog()))
    issues.extend(_managed_user_issues(paths))
    try:
        raw = load_mapping(
            ruleset_path.read_text(encoding="utf-8"),
            name="Rule Set",
        )
    except (OSError, ValueError) as error:
        return CheckReport(
            state=ProjectState.INCOMPATIBLE,
            issues=(_issue("RULESET_INVALID", str(error)),),
        )
    if raw.get("schema_version") != 1:
        return CheckReport(
            state=ProjectState.INCOMPATIBLE,
            issues=(
                _issue(
                    "RULESET_SCHEMA_INCOMPATIBLE",
                    "Rule Set schema is not supported",
                    schema=raw.get("schema_version"),
                ),
            ),
        )
    catalog = load_builtin_catalog()
    try:
        domains_raw = as_mapping(raw.get("domains", {}), name="Rule Set domains")
        domains = as_string_tuple(
            domains_raw.get("core", ()), name="Core domains"
        ) + as_string_tuple(domains_raw.get("profile", ()), name="Profile domains")
        overrides = as_string_tuple(raw.get("overrides", ()), name="Overrides")
    except ValueError as error:
        return CheckReport(
            state=ProjectState.INCOMPATIBLE,
            issues=(_issue("RULESET_INVALID", str(error)),),
        )
    loaded_rule_bytes = 0
    for domain in domains:
        if domain not in catalog.rules:
            issues.append(_issue("RULE_UNKNOWN", f"unknown Rule domain: {domain}"))
            continue
        link = resolved / ".rules" / f"{domain}-rules.md"
        target = paths.rules_home / f"{domain}-rules.md"
        if link.is_file():
            loaded_rule_bytes += len(link.read_bytes())
        if not link_verifier(link, target):
            issues.append(
                _issue(
                    "BASE_LINK_INVALID",
                    f"Base Rule link is missing or targets the wrong file: {domain}",
                    link=str(link),
                    target=str(target),
                )
            )
    agents = resolved / "AGENTS.md"
    agents_text = agents.read_text(encoding="utf-8") if agents.is_file() else ""
    if len(agents_text.encode("utf-8")) > 8192:
        issues.append(_issue("AGENTS_BUDGET_EXCEEDED", "AGENTS.md exceeds 8 KiB"))
    for domain in domains:
        if domain not in catalog.rules:
            continue
        expected = route_row(domain, catalog.rules[domain])
        if expected not in agents_text:
            issues.append(
                _issue(
                    "AGENTS_ROUTE_MISSING",
                    f"AGENTS.md does not route {domain}",
                )
            )
    tracked = (
        {item.replace("\\", "/") for item in tracked_files}
        if tracked_files is not None
        else _git_tracked_files(resolved)
    )
    seen_override_ids: set[str] = set()
    for domain in overrides:
        if domain not in catalog.rules:
            issues.append(_issue("RULE_UNKNOWN", f"unknown Override domain: {domain}"))
            continue
        override = resolved / ".rules" / f"{domain}-rules.override.md"
        relative = override.relative_to(resolved).as_posix()
        if not override.is_file():
            issues.append(_issue("OVERRIDE_MISSING", f"declared Override is missing: {domain}"))
            continue
        if override.is_symlink():
            issues.append(
                _issue("OVERRIDE_NOT_REGULAR", f"Override must be a regular file: {domain}")
            )
        if relative not in tracked:
            issues.append(_issue("OVERRIDE_UNTRACKED", f"Override is not tracked by Git: {domain}"))
        text = override.read_text(encoding="utf-8")
        loaded_rule_bytes += len(text.encode("utf-8"))
        if len(text.encode("utf-8")) > 4096:
            issues.append(_issue("OVERRIDE_BUDGET_EXCEEDED", f"Override exceeds 4 KiB: {domain}"))
        try:
            metadata, body = parse_frontmatter(text)
        except ValueError as error:
            issues.append(
                _issue(
                    "OVERRIDE_FRONTMATTER_INVALID",
                    f"Override frontmatter is invalid: {domain}",
                    error=str(error),
                )
            )
            continue
        base_paths = set(catalog.rules[domain].paths)
        override_paths = set(
            as_string_tuple(metadata.get("paths", ()), name=f"{domain} Override paths")
        )
        if override_paths and not override_paths <= base_paths:
            issues.append(
                _issue(
                    "OVERRIDE_TRIGGER_EXPANDED",
                    f"Override expands the Base trigger: {domain}",
                )
            )
        base = paths.rules_home / f"{domain}-rules.md"
        valid_base_ids: set[str] = (
            set(_BASE_ID.findall(base.read_text(encoding="utf-8"))) if base.is_file() else set()
        )
        operation_issue = _override_operation_issue(
            metadata,
            body,
            domain=domain,
            valid_base_ids=valid_base_ids,
            override_paths=override_paths,
        )
        if operation_issue is not None:
            issues.append(operation_issue)
        for rule_id in _OVERRIDE_ID.findall(body):
            if rule_id in seen_override_ids:
                issues.append(
                    _issue("RULE_ID_DUPLICATE", f"Override Rule ID is duplicated: {rule_id}")
                )
            seen_override_ids.add(rule_id)
    if loaded_rule_bytes > 24 * 1024:
        issues.append(
            _issue(
                "LOADED_RULES_BUDGET_EXCEEDED",
                "selected Base and Override Rules exceed the 24 KiB cumulative budget",
                bytes=loaded_rule_bytes,
            )
        )
    version_state = (
        ProjectState.UPDATE_AVAILABLE
        if str(raw.get("rules_version")) != catalog.rules_version
        else ProjectState.HEALTHY
    )
    return CheckReport(
        state=ProjectState.DRIFTED if issues else version_state,
        issues=tuple(issues),
    )
