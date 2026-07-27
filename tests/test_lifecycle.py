from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import cast

import pytest

from project_execution_rules.catalog import load_builtin_catalog
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.install import install_user_resources, plan_user_install
from project_execution_rules.lifecycle import (
    apply_lifecycle_plan,
    plan_project_update,
    plan_repair,
    plan_rollback,
    plan_uninstall,
    plan_update,
    plan_user_uninstall,
    rollback_transaction,
    summarize_update,
)
from project_execution_rules.managed import ManagedManifest, ManagedSelection
from project_execution_rules.models import AdapterId, Change, ChangePlan
from project_execution_rules.paths import UserPaths
from project_execution_rules.transactions import FileTransaction


def _paths(tmp_path: Path) -> UserPaths:
    return UserPaths.from_environment(
        {"LOCALAPPDATA": str(tmp_path / "local")},
        tmp_path / "home",
    )


def test_update_plan_is_dry_run_and_contains_user_resources(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    plan = plan_update(paths, load_builtin_catalog())

    assert plan.scope == "user"
    assert plan.changes
    assert not paths.rules_home.exists()


def test_update_summary_reports_override_impact_for_modified_base(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    catalog = load_builtin_catalog()
    install_user_resources(plan_user_install(paths, catalog), paths, confirmed=True)
    (paths.rules_home / "python-rules.md").write_text("changed\n", encoding="utf-8")
    root = tmp_path / "project"
    rules = root / ".rules"
    rules.mkdir(parents=True)
    (rules / "python-rules.override.md").write_text("# Override\n", encoding="utf-8")

    summary = summarize_update(root, paths, catalog)
    rules_summary = cast(dict[str, object], summary["rules"])

    assert "python" in cast(list[str], rules_summary["modified"])
    assert summary["override_impact"] == ["python"]
    assert summary["schema_compatible"] is True


def test_repair_plan_only_targets_managed_structure(tmp_path: Path) -> None:
    root = tmp_path / "project"
    rules = root / ".rules"
    rules.mkdir(parents=True)
    (rules / "ruleset.yaml").write_text(
        """schema_version: 2
rules_version: 1.0.0
adapters:
  - codex
profile: python
domains:
  core:
    - security
  profile:
    - python
overrides:
  codex:
    - python
""",
        encoding="utf-8",
    )
    (rules / "python-rules.override.md").write_text(
        "# Python Rule Overrides\n\n- `PY-OVR-001`：保留。\n",
        encoding="utf-8",
    )
    paths = _paths(tmp_path)
    paths.rules_home.mkdir(parents=True)
    for domain in ("security", "python"):
        (paths.rules_home / f"{domain}-rules.md").write_text("base", encoding="utf-8")

    plan = plan_repair(root, paths, link_verifier=lambda link, target: False)

    names = {change.target.name for change in plan.changes}
    assert {"security-rules.md", "python-rules.md"} <= names
    assert "python-rules.override.md" not in names


def test_project_repair_refuses_missing_user_rule(tmp_path: Path) -> None:
    root = tmp_path / "project"
    rules = root / ".rules"
    rules.mkdir(parents=True)
    (rules / "ruleset.yaml").write_text(
        """schema_version: 2
rules_version: 1.0.0
adapters:
  - codex
profile: python
domains:
  core:
    - security
  profile: []
overrides:
  codex: []
""",
        encoding="utf-8",
    )
    paths = _paths(tmp_path)
    plan = plan_repair(root, paths, link_verifier=lambda link, target: False)

    with pytest.raises(ProjectRulesError, match="missing or drifted user Rule"):
        apply_lifecycle_plan(plan, root, paths, confirmed=True)


def test_uninstall_preserves_overrides(tmp_path: Path) -> None:
    root = tmp_path / "project"
    rules = root / ".rules"
    rules.mkdir(parents=True)
    (rules / "ruleset.yaml").write_text(
        """schema_version: 2
rules_version: 1.0.0
adapters:
  - codex
profile: python
domains:
  core:
    - security
  profile:
    - python
overrides:
  codex:
    - python
""",
        encoding="utf-8",
    )
    override = rules / "python-rules.override.md"
    override.write_text("# Override\n", encoding="utf-8")

    plan = plan_uninstall(root, _paths(tmp_path), include_user=False)

    assert override not in {change.target for change in plan.changes}
    assert rules / "ruleset.yaml" in {change.target for change in plan.changes}


def test_uninstall_refuses_regular_file_in_managed_link_slot(tmp_path: Path) -> None:
    root = tmp_path / "project"
    rules = root / ".rules"
    rules.mkdir(parents=True)
    (rules / "ruleset.yaml").write_text(
        """schema_version: 2
rules_version: 1.0.0
adapters:
  - codex
profile: python
domains:
  core:
    - security
  profile: []
overrides:
  codex: []
""",
        encoding="utf-8",
    )
    (rules / "security-rules.md").write_text("user content\n", encoding="utf-8")

    with pytest.raises(ProjectRulesError, match="non-managed"):
        plan_uninstall(root, _paths(tmp_path), include_user=False)


def test_project_update_changes_only_declared_rules_version(tmp_path: Path) -> None:
    root = tmp_path / "project"
    rules = root / ".rules"
    rules.mkdir(parents=True)
    ruleset = rules / "ruleset.yaml"
    ruleset.write_text(
        """schema_version: 2
rules_version: 0.9.0
adapters:
  - codex
profile: python
domains:
  core:
    - security
  profile:
    - python
overrides:
  codex:
    - python
""",
        encoding="utf-8",
    )

    plan = plan_project_update(root, load_builtin_catalog())

    assert len(plan.changes) == 1
    content = plan.changes[0].content.decode()
    assert "rules_version: 1.0.0" in content
    assert "overrides:\n  codex:\n  - python" in content


def test_user_uninstall_is_a_separate_scope(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    manifest = paths.manifest_path(AdapterId.CODEX)
    ManagedManifest(
        schema_version=2,
        adapter=AdapterId.CODEX,
        resource_version="1.0.0",
        selection=ManagedSelection(rules=(), skills=(), agents=()),
        entries=(),
    ).save(manifest)

    plan = plan_user_uninstall(paths)

    assert plan.scope == "user"
    assert {change.target for change in plan.changes} == {manifest}


def _write_restore_transaction(
    paths: UserPaths,
    *,
    root: Path,
    target: Path,
    adapter: object = None,
    include_adapter: bool = False,
) -> None:
    transaction_home = paths.transactions_home / "deadbeef"
    backup_home = paths.backups_home / "deadbeef"
    transaction_home.mkdir(parents=True)
    backup_home.mkdir(parents=True)
    backup = backup_home / "0.bin"
    backup.write_bytes(b"original\n")
    payload: dict[str, object] = {
        "authorized_root": str(root),
        "originals": [
            {
                "target": target.relative_to(root).as_posix(),
                "kind": "file",
                "backup": str(backup),
                "link_target": "",
            }
        ],
    }
    if include_adapter:
        payload["adapter"] = adapter
    (transaction_home / "manifest.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("adapter", "include_adapter"),
    (("claude", True), (None, False), ("invalid", True)),
)
def test_adapter_rollback_rejects_bad_metadata_before_modifying_target(
    tmp_path: Path,
    adapter: object,
    include_adapter: bool,
) -> None:
    root = tmp_path / "home"
    root.mkdir()
    target = root / "managed.md"
    target.write_text("changed\n", encoding="utf-8")
    paths = _paths(tmp_path)
    _write_restore_transaction(
        paths,
        root=root,
        target=target,
        adapter=adapter,
        include_adapter=include_adapter,
    )

    with pytest.raises(ProjectRulesError, match="Adapter"):
        rollback_transaction(paths, "deadbeef", expected_adapter=AdapterId.CODEX)

    assert target.read_text(encoding="utf-8") == "changed\n"


def test_non_adapter_rollback_allows_legacy_manifest_without_adapter(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    target = root / "AGENTS.md"
    target.write_text("changed\n", encoding="utf-8")
    paths = _paths(tmp_path)
    _write_restore_transaction(paths, root=root, target=target)

    rollback_transaction(paths, "deadbeef")

    assert target.read_text(encoding="utf-8") == "original\n"


def test_user_lifecycle_transaction_persists_codex_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    target = paths.rules_home / "security-rules.md"
    plan = ChangePlan(
        scope="user",
        changes=(Change(action="write", target=target, content=b"rule\n"),),
    )

    def preserve_transaction(_: FileTransaction) -> None:
        return None

    monkeypatch.setattr(FileTransaction, "cleanup", preserve_transaction)

    report = apply_lifecycle_plan(plan, tmp_path / "project", paths, confirmed=True)
    assert report.transaction_id is not None
    raw = json.loads(
        (paths.transactions_home / report.transaction_id / "manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert raw["adapter"] == "codex"


def test_rollback_rejects_unknown_transaction(tmp_path: Path) -> None:
    with pytest.raises(ProjectRulesError, match="transaction does not exist"):
        rollback_transaction(_paths(tmp_path), "deadbeef")


def test_rollback_rejects_parent_junction_escape(tmp_path: Path) -> None:
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    junction = root / "redirect"
    try:
        junction.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("directory symlink privilege is unavailable")
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip("directory junction creation is unavailable")
    escaped = outside / "escaped.txt"
    escaped.write_text("outside\n", encoding="utf-8")
    paths = _paths(tmp_path)
    transaction_home = paths.transactions_home / "deadbeef"
    transaction_home.mkdir(parents=True)
    (transaction_home / "manifest.json").write_text(
        json.dumps(
            {
                "authorized_root": str(root),
                "originals": [
                    {
                        "target": "redirect/escaped.txt",
                        "kind": "missing",
                        "backup": "",
                        "link_target": "",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProjectRulesError, match="outside authorized root"):
        rollback_transaction(paths, "deadbeef")

    assert escaped.read_text(encoding="utf-8") == "outside\n"


def test_rollback_preserves_evidence_when_restore_verification_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    target = root / "AGENTS.md"
    target.write_text("changed\n", encoding="utf-8")
    paths = _paths(tmp_path)
    transaction_home = paths.transactions_home / "deadbeef"
    backup_home = paths.backups_home / "deadbeef"
    transaction_home.mkdir(parents=True)
    backup_home.mkdir(parents=True)
    backup = backup_home / "0.bin"
    backup.write_bytes(b"original\n")
    (transaction_home / "manifest.json").write_text(
        json.dumps(
            {
                "authorized_root": str(root),
                "originals": [
                    {
                        "target": "AGENTS.md",
                        "kind": "file",
                        "backup": str(backup),
                        "link_target": "",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    original_write_bytes = Path.write_bytes

    def corrupt_target(path: Path, data: bytes) -> int:
        if path == target:
            return original_write_bytes(path, b"corrupt\n")
        return original_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", corrupt_target)

    with pytest.raises(ProjectRulesError, match="rollback verification failed"):
        rollback_transaction(paths, "deadbeef")

    assert transaction_home.exists()
    assert backup_home.exists()


def test_rollback_dry_run_plan_uses_manifest_targets(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    paths = _paths(tmp_path)
    transaction_home = paths.transactions_home / "deadbeef"
    transaction_home.mkdir(parents=True)
    (transaction_home / "manifest.json").write_text(
        json.dumps(
            {
                "authorized_root": str(root),
                "originals": [
                    {
                        "target": "AGENTS.md",
                        "kind": "missing",
                        "backup": "",
                        "link_target": "",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    plan = plan_rollback(paths, "deadbeef")

    assert plan.scope == "rollback"
    assert plan.changes[0].action == "remove"
    assert plan.changes[0].target == root / "AGENTS.md"
