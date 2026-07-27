from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from project_execution_rules.errors import TransactionError
from project_execution_rules.transactions import FileTransaction


def test_failed_verification_restores_original(tmp_path: Path) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_text("original", encoding="utf-8")
    transaction = FileTransaction(tmp_path / "state", tmp_path)
    transaction.plan_write(target, b"changed")

    with pytest.raises(TransactionError, match="verification failed"):
        transaction.apply(lambda: False)

    assert target.read_text(encoding="utf-8") == "original"


def test_transaction_rejects_target_outside_authorized_root(tmp_path: Path) -> None:
    transaction = FileTransaction(tmp_path / "state", tmp_path / "project")

    with pytest.raises(TransactionError, match="outside authorized root"):
        transaction.plan_write(tmp_path / "other" / "file.txt", b"data")


def test_successful_transaction_can_be_cleaned_up(tmp_path: Path) -> None:
    target = tmp_path / "ruleset.yaml"
    transaction = FileTransaction(tmp_path / "state", tmp_path)
    transaction.plan_write(target, b"schema_version: 1\n")

    transaction.apply(lambda: target.is_file())
    transaction.cleanup()

    assert target.read_text(encoding="utf-8") == "schema_version: 1\n"
    assert not transaction.transaction_home.exists()


def test_transaction_manifest_uses_relative_logical_targets(tmp_path: Path) -> None:
    root = tmp_path / "project"
    target = root / ".rules" / "ruleset.yaml"
    transaction = FileTransaction(tmp_path / "state", root)
    transaction.plan_write(target, b"schema_version: 1\n")

    transaction.apply(lambda: target.is_file())
    manifest = json.loads(
        (transaction.transaction_home / "manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["operations"][0]["target"] == ".rules/ruleset.yaml"
    assert manifest["originals"][0]["target"] == ".rules/ruleset.yaml"


def test_symlink_operation_uses_exact_target(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("rule", encoding="utf-8")
    link = tmp_path / "project" / "rule.md"
    calls: list[tuple[str, Path]] = []

    def create_symlink(link_target: str, target: Path) -> None:
        calls.append((link_target, target))

    transaction = FileTransaction(
        tmp_path / "state",
        tmp_path / "project",
        symlink_factory=create_symlink,
    )
    transaction.plan_symlink(link, source)

    transaction.apply(lambda: True)

    assert calls == [(str(source.resolve()), link.absolute())]


def test_transaction_rejects_parent_symlink_escape(tmp_path: Path) -> None:
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
    transaction = FileTransaction(tmp_path / "state", root)

    with pytest.raises(TransactionError, match="outside authorized root"):
        transaction.plan_write(junction / "escaped.txt", b"escaped")

    assert not (outside / "escaped.txt").exists()
