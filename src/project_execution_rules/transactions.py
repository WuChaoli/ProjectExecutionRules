from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from project_execution_rules.errors import TransactionError
from project_execution_rules.models import AdapterId


@dataclass(frozen=True, slots=True)
class _Operation:
    kind: str
    target: str
    content_hex: str = ""
    link_target: str = ""


@dataclass(frozen=True, slots=True)
class _Original:
    target: str
    kind: str
    backup: str = ""
    link_target: str = ""


def resolve_target_within_root(
    target: Path,
    authorized_root: Path,
    *,
    lexical_root: Path | None = None,
) -> Path:
    root = authorized_root.resolve()
    lexical = Path(os.path.abspath(lexical_root or authorized_root))
    candidate = Path(os.path.abspath(target))
    try:
        try:
            candidate.relative_to(lexical)
        except ValueError:
            candidate.relative_to(root)
        canonical_parent = candidate.parent.resolve(strict=False)
        canonical_parent.relative_to(root)
    except ValueError as error:
        raise TransactionError(
            "TARGET_OUTSIDE_ROOT",
            f"target is outside authorized root: {candidate}",
            evidence={"target": str(candidate), "root": str(root)},
        ) from error
    return canonical_parent / candidate.name


class FileTransaction:
    """Apply exact file operations with a verified restore path."""

    def __init__(
        self,
        state_home: Path,
        authorized_root: Path,
        *,
        adapter: AdapterId | str | None = None,
        symlink_factory: Callable[[str, Path], None] = os.symlink,
    ) -> None:
        self.state_home = state_home.resolve()
        self.lexical_root = Path(os.path.abspath(authorized_root))
        self.authorized_root = authorized_root.resolve()
        self.adapter = AdapterId(adapter) if adapter is not None else None
        self.transaction_id = uuid.uuid4().hex
        self.transaction_home = self.state_home / "transactions" / self.transaction_id
        self.backup_home = self.state_home / "backups" / self.transaction_id
        self._operations: list[_Operation] = []
        self._originals: list[_Original] = []
        self._applied = False
        self._symlink_factory = symlink_factory

    def _validate_target(self, target: Path) -> Path:
        return resolve_target_within_root(
            target,
            self.authorized_root,
            lexical_root=self.lexical_root,
        )

    def _logical_target(self, target: Path) -> str:
        return self._validate_target(target).relative_to(self.authorized_root).as_posix()

    def _target_path(self, logical_target: str) -> Path:
        logical = Path(logical_target)
        if logical.is_absolute() or ".." in logical.parts:
            raise TransactionError(
                "TRANSACTION_TARGET_INVALID",
                f"transaction target is not relative: {logical_target}",
            )
        return self._validate_target(self.authorized_root / logical)

    def _backup_bytes(self, backup: str) -> bytes:
        path = resolve_target_within_root(Path(backup), self.backup_home)
        if path.is_symlink() or not path.is_file():
            raise TransactionError(
                "TRANSACTION_BACKUP_INVALID",
                f"transaction backup is not a regular file: {path}",
            )
        return path.read_bytes()

    def plan_write(self, target: Path, content: bytes) -> None:
        self._operations.append(
            _Operation(
                kind="write",
                target=self._logical_target(target),
                content_hex=content.hex(),
            )
        )

    def plan_symlink(self, target: Path, link_target: Path) -> None:
        self._operations.append(
            _Operation(
                kind="symlink",
                target=self._logical_target(target),
                link_target=str(link_target.resolve()),
            )
        )

    def plan_remove(self, target: Path) -> None:
        self._operations.append(_Operation(kind="remove", target=self._logical_target(target)))

    def _backup(self) -> None:
        self.transaction_home.mkdir(parents=True, exist_ok=False)
        self.backup_home.mkdir(parents=True, exist_ok=False)
        originals: list[_Original] = []
        for index, operation in enumerate(self._operations):
            target = self._target_path(operation.target)
            if target.is_symlink():
                originals.append(
                    _Original(
                        target=operation.target,
                        kind="symlink",
                        link_target=os.readlink(target),
                    )
                )
            elif target.is_file():
                backup = self.backup_home / f"{index}.bin"
                backup.write_bytes(target.read_bytes())
                originals.append(
                    _Original(
                        target=operation.target,
                        kind="file",
                        backup=str(backup),
                    )
                )
            elif target.exists():
                raise TransactionError(
                    "UNSUPPORTED_TARGET",
                    f"managed target is not a file or symlink: {target}",
                )
            else:
                originals.append(_Original(target=operation.target, kind="missing"))
        self._originals = originals
        payload = {
            "transaction_id": self.transaction_id,
            "authorized_root": str(self.authorized_root),
            "operations": [asdict(item) for item in self._operations],
            "originals": [asdict(item) for item in originals],
            "status": "backed_up",
        }
        if self.adapter is not None:
            payload["adapter"] = self.adapter.value
        (self.transaction_home / "manifest.json").write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )

    def _validate_manifest_adapter(self) -> None:
        if self.adapter is None:
            return
        manifest_path = self.transaction_home / "manifest.json"
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            actual = AdapterId(raw["adapter"])
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise TransactionError(
                "TRANSACTION_ADAPTER_INVALID",
                f"transaction Adapter metadata is invalid: {manifest_path}",
                evidence={"expected_adapter": self.adapter.value},
            ) from error
        if actual is not self.adapter:
            raise TransactionError(
                "TRANSACTION_ADAPTER_MISMATCH",
                f"transaction belongs to Adapter {actual.value}, not {self.adapter.value}",
                evidence={
                    "expected_adapter": self.adapter.value,
                    "actual_adapter": actual.value,
                },
            )

    @staticmethod
    def _unlink_file(target: Path) -> None:
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.exists():
            raise TransactionError(
                "UNSUPPORTED_TARGET",
                f"refusing to remove non-file target: {target}",
            )

    def _apply_operations(self) -> None:
        for operation in self._operations:
            target = self._target_path(operation.target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target = self._validate_target(target)
            self._unlink_file(target)
            if operation.kind == "write":
                target.write_bytes(bytes.fromhex(operation.content_hex))
            elif operation.kind == "symlink":
                self._symlink_factory(operation.link_target, target)
            elif operation.kind != "remove":
                raise TransactionError(
                    "UNKNOWN_OPERATION",
                    f"unknown transaction operation: {operation.kind}",
                )

    def restore(self) -> None:
        self._validate_manifest_adapter()
        for original in reversed(self._originals):
            target = self._target_path(original.target)
            self._unlink_file(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target = self._validate_target(target)
            if original.kind == "file":
                target.write_bytes(self._backup_bytes(original.backup))
            elif original.kind == "symlink":
                self._symlink_factory(original.link_target, target)
            elif original.kind != "missing":
                raise TransactionError(
                    "RESTORE_KIND_INVALID",
                    f"unknown restore kind: {original.kind}",
                )
        for original in self._originals:
            target = self._target_path(original.target)
            if original.kind == "file":
                restored = (
                    not target.is_symlink()
                    and target.is_file()
                    and target.read_bytes() == self._backup_bytes(original.backup)
                )
            elif original.kind == "symlink":
                restored = target.is_symlink() and os.readlink(target) == original.link_target
            else:
                restored = not target.exists() and not target.is_symlink()
            if not restored:
                raise TransactionError(
                    "RESTORE_VERIFY_FAILED",
                    f"restored target verification failed: {target}",
                )
        self._applied = False

    def apply(self, verify: Callable[[], bool]) -> None:
        self._backup()
        try:
            self._apply_operations()
            self._applied = True
            if not verify():
                raise TransactionError(
                    "TRANSACTION_VERIFY_FAILED",
                    "transaction verification failed",
                )
        except Exception as error:
            try:
                self.restore()
            except Exception as restore_error:
                raise TransactionError(
                    "TRANSACTION_RESTORE_FAILED",
                    "transaction failed and restoration failed",
                    evidence={"restore_error": str(restore_error)},
                ) from restore_error
            if isinstance(error, TransactionError):
                raise
            raise TransactionError(
                "TRANSACTION_APPLY_FAILED",
                f"transaction apply failed: {error}",
            ) from error

    def cleanup(self) -> None:
        if not self._applied:
            raise TransactionError(
                "TRANSACTION_NOT_VERIFIED",
                "cannot cleanup a transaction that is not verified",
            )
        for path in (self.transaction_home, self.backup_home):
            if path.exists():
                resolved = path.resolve()
                resolved.relative_to(self.state_home)
                shutil.rmtree(resolved)
