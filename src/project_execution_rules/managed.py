from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import cast

from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.models import AdapterId

_SCHEMA_VERSION = 2
_ENTRY_KINDS = {"rule", "skill", "agent"}
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_SELECTION_KEYS = {"rules", "skills", "agents"}
_MANIFEST_KEYS = {"schema_version", "adapter", "resource_version", "selection", "entries"}
_ENTRY_KEYS = {"logical_path", "kind", "sha256"}


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True, slots=True)
class ManagedEntry:
    logical_path: str
    kind: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ManagedSelection:
    rules: tuple[str, ...]
    skills: tuple[str, ...]
    agents: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "rules", tuple(sorted(self.rules)))
        object.__setattr__(self, "skills", tuple(sorted(self.skills)))
        object.__setattr__(self, "agents", tuple(sorted(self.agents)))


@dataclass(frozen=True, slots=True)
class ManagedManifest:
    schema_version: int
    adapter: AdapterId
    resource_version: str
    selection: ManagedSelection
    entries: tuple[ManagedEntry, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter", AdapterId(self.adapter))
        object.__setattr__(
            self,
            "entries",
            tuple(sorted(self.entries, key=lambda entry: (entry.logical_path, entry.kind))),
        )

    def to_bytes(self, path: Path) -> bytes:
        _validate_manifest(self, path)
        payload = {
            "schema_version": self.schema_version,
            "adapter": self.adapter.value,
            "resource_version": self.resource_version,
            "selection": {
                "rules": list(self.selection.rules),
                "skills": list(self.selection.skills),
                "agents": list(self.selection.agents),
            },
            "entries": [asdict(entry) for entry in self.entries],
        }
        return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()

    def save(self, path: Path) -> None:
        content = self.to_bytes(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        expected_adapter: AdapterId | str | None = None,
    ) -> ManagedManifest:
        try:
            raw = cast(object, json.loads(path.read_text(encoding="utf-8")))
            if not isinstance(raw, dict):
                raise ValueError("manifest must be an object")
            manifest_raw = cast(dict[str, object], raw)
            if set(manifest_raw) != _MANIFEST_KEYS:
                raise ValueError("manifest must contain exactly the v2 fields")
            schema_version = manifest_raw["schema_version"]
            if type(schema_version) is not int or schema_version != _SCHEMA_VERSION:
                raise ValueError("schema_version must be 2")
            adapter = AdapterId(_require_string(manifest_raw["adapter"], "adapter"))
            selection_value = manifest_raw["selection"]
            if not isinstance(selection_value, dict):
                raise ValueError("selection must be an object")
            selection_raw = cast(dict[str, object], selection_value)
            if set(selection_raw) != _SELECTION_KEYS:
                raise ValueError("selection must contain rules, skills, and agents")
            entries_value = manifest_raw["entries"]
            if not isinstance(entries_value, list):
                raise ValueError("entries must be an array")
            entries_raw = cast(list[object], entries_value)
            entries: list[ManagedEntry] = []
            for entry_value in entries_raw:
                if not isinstance(entry_value, dict):
                    raise ValueError("each entry must be an object")
                entry_raw = cast(dict[str, object], entry_value)
                if set(entry_raw) != _ENTRY_KEYS:
                    raise ValueError("each entry must contain logical_path, kind, and sha256")
                entries.append(
                    ManagedEntry(
                        logical_path=_require_string(entry_raw["logical_path"], "logical_path"),
                        kind=_require_string(entry_raw["kind"], "kind"),
                        sha256=_require_string(entry_raw["sha256"], "sha256"),
                    )
                )
            manifest = cls(
                schema_version=schema_version,
                adapter=adapter,
                resource_version=_require_string(
                    manifest_raw["resource_version"], "resource_version"
                ),
                selection=ManagedSelection(
                    rules=_require_string_tuple(selection_raw["rules"], "selection.rules"),
                    skills=_require_string_tuple(selection_raw["skills"], "selection.skills"),
                    agents=_require_string_tuple(selection_raw["agents"], "selection.agents"),
                ),
                entries=tuple(entries),
            )
            _validate_manifest(manifest, path)
            if expected_adapter is not None:
                expected = AdapterId(expected_adapter)
                if manifest.adapter is not expected:
                    raise ProjectRulesError(
                        "MANAGED_MANIFEST_ADAPTER_MISMATCH",
                        f"managed resource manifest belongs to {manifest.adapter.value}, "
                        f"not {expected.value}",
                        evidence={
                            "expected_adapter": expected.value,
                            "actual_adapter": manifest.adapter.value,
                        },
                        remediation="Use the manifest for the requested Adapter.",
                    )
            return manifest
        except ProjectRulesError:
            raise
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise _invalid_manifest_error(path, str(error)) from error


def is_safe_adapter_path(target: Path, *, adapter_home: Path) -> bool:
    lexical_target = Path(os.path.abspath(target))
    lexical_home = Path(os.path.abspath(adapter_home))
    try:
        lexical_target.relative_to(lexical_home)
    except ValueError:
        return False

    current = lexical_target
    while True:
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            pass
        except OSError:
            return False
        else:
            if current.is_symlink() or (
                getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            ):
                return False
        if current == lexical_home:
            break
        if current.parent == current:
            return False
        current = current.parent

    try:
        lexical_target.parent.resolve(strict=False).relative_to(
            lexical_home.resolve(strict=False)
        )
        return True
    except (OSError, ValueError):
        return False


def is_safe_adapter_file(target: Path, *, adapter_home: Path) -> bool:
    if not is_safe_adapter_path(target, adapter_home=adapter_home):
        return False
    try:
        target.resolve(strict=True).relative_to(adapter_home.resolve(strict=True))
        return target.is_file()
    except (OSError, ValueError):
        return False


def is_current_managed_file(
    target: Path,
    *,
    expected_adapter: AdapterId | str,
    adapter_home: Path,
    manifest_path: Path,
) -> bool:
    if not is_safe_adapter_file(target, adapter_home=adapter_home) or not manifest_path.is_file():
        return False
    try:
        logical = target.resolve(strict=True).relative_to(
            adapter_home.resolve(strict=True)
        ).as_posix()
        manifest = ManagedManifest.load(
            manifest_path,
            expected_adapter=expected_adapter,
        )
        expected = next(
            (entry.sha256 for entry in manifest.entries if entry.logical_path == logical),
            None,
        )
        return expected is not None and sha256_bytes(target.read_bytes()) == expected
    except (OSError, ValueError, ProjectRulesError):
        return False


def _validate_manifest(manifest: ManagedManifest, path: Path) -> None:
    if type(manifest.schema_version) is not int or manifest.schema_version != _SCHEMA_VERSION:
        raise _invalid_manifest_error(path, "schema_version must be 2")
    resource_version = cast(object, manifest.resource_version)
    if not isinstance(resource_version, str) or not resource_version:
        raise _invalid_manifest_error(path, "resource_version must be a non-empty string")
    expected_name = f"managed-user-{manifest.adapter.value}.json"
    if path.name != expected_name:
        raise ProjectRulesError(
            "MANAGED_MANIFEST_PATH_MISMATCH",
            f"managed resource manifest path does not match Adapter {manifest.adapter.value}",
            evidence={"adapter": manifest.adapter.value, "path": str(path)},
            remediation=f"Use a manifest named {expected_name}.",
        )
    for field_name in ("rules", "skills", "agents"):
        values = getattr(manifest.selection, field_name)
        if any(not isinstance(value, str) or not value for value in values):
            raise _invalid_manifest_error(path, f"selection.{field_name} must contain strings")
        if len(values) != len(set(values)):
            raise _invalid_manifest_error(path, f"selection.{field_name} contains duplicates")
    seen_paths: set[str] = set()
    for entry in manifest.entries:
        logical_path = cast(object, entry.logical_path)
        kind = cast(object, entry.kind)
        digest = cast(object, entry.sha256)
        evidence: dict[str, object] = {"logical_path": logical_path}
        if not isinstance(logical_path, str):
            raise _invalid_manifest_error(
                path,
                "entry logical_path must be a string",
                evidence=evidence,
            )
        if not _is_posix_relative_path(logical_path):
            raise _invalid_manifest_error(
                path,
                "entry logical_path must be a normalized POSIX relative path",
                evidence=evidence,
            )
        if not isinstance(kind, str) or kind not in _ENTRY_KINDS:
            raise _invalid_manifest_error(
                path,
                "entry kind must be rule, skill, or agent",
                evidence=evidence,
            )
        if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
            raise _invalid_manifest_error(
                path,
                "entry sha256 must be 64 lowercase hexadecimal characters",
                evidence=evidence,
            )
        if logical_path in seen_paths:
            raise _invalid_manifest_error(path, "duplicate managed entry", evidence=evidence)
        seen_paths.add(logical_path)


def _is_posix_relative_path(value: str) -> bool:
    if not value or "\\" in value:
        return False
    logical = PurePosixPath(value)
    return (
        bool(logical.parts)
        and not logical.is_absolute()
        and logical.as_posix() == value
        and all(part not in {"", ".", ".."} for part in logical.parts)
        and not logical.parts[0].endswith(":")
    )


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    return value


def _require_string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{field} must be an array of strings")
    items = cast(list[object], value)
    if any(not isinstance(item, str) for item in items):
        raise TypeError(f"{field} must be an array of strings")
    return tuple(cast(str, item) for item in items)


def _invalid_manifest_error(
    path: Path,
    reason: str,
    *,
    evidence: Mapping[str, object] | None = None,
) -> ProjectRulesError:
    details = dict(evidence or {})
    details["error"] = reason
    return ProjectRulesError(
        "MANAGED_MANIFEST_INVALID",
        f"managed resource manifest is invalid: {path}",
        evidence=details,
        remediation="Restore the manifest from backup or reinstall managed resources.",
    )
