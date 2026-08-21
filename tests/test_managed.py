from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.managed import (
    ManagedEntry,
    ManagedManifest,
    ManagedSelection,
    is_current_managed_file,
    sha256_bytes,
)
from project_execution_rules.models import AdapterId


def _manifest(*entries: ManagedEntry, adapter: AdapterId = AdapterId.CLAUDE) -> ManagedManifest:
    return ManagedManifest(
        schema_version=2,
        adapter=adapter,
        resource_version="1.0.0",
        selection=ManagedSelection(
            rules=("security", "architecture"),
            skills=("git", "architecture"),
            agents=("rules-reviewer",),
        ),
        entries=entries
        or (
            ManagedEntry("skills/git/SKILL.md", "skill", "1" * 64),
            ManagedEntry("rules/security.md", "rule", "0" * 64),
        ),
    )


def _write_raw(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_manifest_round_trip_keeps_adapter_and_selection(tmp_path: Path) -> None:
    manifest = _manifest()
    path = tmp_path / "managed-user-claude.json"

    manifest.save(path)

    assert ManagedManifest.load(path, expected_adapter=AdapterId.CLAUDE) == manifest
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 2
    assert raw["adapter"] == "claude"
    assert raw["selection"] == {
        "rules": ["architecture", "security"],
        "skills": ["architecture", "git"],
        "agents": ["rules-reviewer"],
    }
    assert [entry["logical_path"] for entry in raw["entries"]] == [
        "rules/security.md",
        "skills/git/SKILL.md",
    ]


def test_manifest_load_rejects_unexpected_adapter(tmp_path: Path) -> None:
    path = tmp_path / "managed-user-claude.json"
    _manifest().save(path)

    with pytest.raises(ProjectRulesError) as raised:
        ManagedManifest.load(path, expected_adapter=AdapterId.CODEX)

    assert raised.value.code == "MANAGED_MANIFEST_ADAPTER_MISMATCH"
    assert raised.value.evidence == {"expected_adapter": "codex", "actual_adapter": "claude"}


def test_manifest_save_rejects_adapter_path_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "managed-user-codex.json"

    with pytest.raises(ProjectRulesError) as raised:
        _manifest().save(path)

    assert raised.value.code == "MANAGED_MANIFEST_PATH_MISMATCH"
    assert raised.value.evidence["adapter"] == "claude"
    assert raised.value.evidence["path"] == str(path)


@pytest.mark.parametrize(
    ("logical_path", "kind", "digest"),
    (
        ("/rules/security.md", "rule", "0" * 64),
        (".", "rule", "0" * 64),
        ("rules/../security.md", "rule", "0" * 64),
        (r"rules\security.md", "rule", "0" * 64),
        ("rules/security.md", "file", "0" * 64),
        ("rules/security.md", "rule", "A" * 64),
        ("rules/security.md", "rule", "0" * 63),
    ),
)
def test_manifest_save_rejects_invalid_entry(
    tmp_path: Path,
    logical_path: str,
    kind: str,
    digest: str,
) -> None:
    manifest = _manifest(ManagedEntry(logical_path, kind, digest))

    with pytest.raises(ProjectRulesError) as raised:
        manifest.save(tmp_path / "managed-user-claude.json")

    assert raised.value.code == "MANAGED_MANIFEST_INVALID"
    assert raised.value.evidence["logical_path"] == logical_path


def test_manifest_save_rejects_invalid_field_types(tmp_path: Path) -> None:
    invalid_manifests = (
        ManagedManifest(
            schema_version=cast(int, 2.0),
            adapter=AdapterId.CLAUDE,
            resource_version="1.0.0",
            selection=ManagedSelection((), (), ()),
            entries=(),
        ),
        ManagedManifest(
            schema_version=2,
            adapter=AdapterId.CLAUDE,
            resource_version=cast(str, 1),
            selection=ManagedSelection((), (), ()),
            entries=(),
        ),
        _manifest(ManagedEntry(cast(str, 1), "rule", "0" * 64)),
        _manifest(ManagedEntry("rules/security.md", cast(str, 1), "0" * 64)),
        _manifest(ManagedEntry("rules/security.md", "rule", cast(str, 1))),
    )

    for manifest in invalid_manifests:
        with pytest.raises(ProjectRulesError) as raised:
            manifest.save(tmp_path / "managed-user-claude.json")
        assert raised.value.code == "MANAGED_MANIFEST_INVALID"
        assert "error" in raised.value.evidence


def test_manifest_load_rejects_duplicate_entries(tmp_path: Path) -> None:
    path = tmp_path / "managed-user-claude.json"
    entry = {"logical_path": "rules/security.md", "kind": "rule", "sha256": "0" * 64}
    _write_raw(
        path,
        {
            "schema_version": 2,
            "adapter": "claude",
            "resource_version": "1.0.0",
            "selection": {"rules": [], "skills": [], "agents": []},
            "entries": [entry, entry],
        },
    )

    with pytest.raises(ProjectRulesError) as raised:
        ManagedManifest.load(path)

    assert raised.value.code == "MANAGED_MANIFEST_INVALID"
    assert raised.value.evidence["logical_path"] == "rules/security.md"


def test_is_current_managed_file_checks_adapter_root_and_symlink(tmp_path: Path) -> None:
    adapter_home = tmp_path / ".claude"
    target = adapter_home / "rules" / "security.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"security")
    manifest_path = tmp_path / "state" / "managed-user-claude.json"
    _manifest(ManagedEntry("rules/security.md", "rule", sha256_bytes(target.read_bytes()))).save(
        manifest_path
    )

    assert is_current_managed_file(
        target,
        expected_adapter=AdapterId.CLAUDE,
        adapter_home=adapter_home,
        manifest_path=manifest_path,
    )
    assert not is_current_managed_file(
        target,
        expected_adapter=AdapterId.CODEX,
        adapter_home=adapter_home,
        manifest_path=manifest_path,
    )
    assert not is_current_managed_file(
        target,
        expected_adapter=AdapterId.CLAUDE,
        adapter_home=adapter_home / "rules",
        manifest_path=manifest_path,
    )

    link = adapter_home / "rules" / "security-link.md"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is not available")
    link_manifest = _manifest(
        ManagedEntry("rules/security-link.md", "rule", sha256_bytes(target.read_bytes()))
    )
    link_manifest.save(manifest_path)
    assert not is_current_managed_file(
        link,
        expected_adapter=AdapterId.CLAUDE,
        adapter_home=adapter_home,
        manifest_path=manifest_path,
    )
