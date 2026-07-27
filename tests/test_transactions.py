from __future__ import annotations

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
