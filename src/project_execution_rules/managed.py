from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True, slots=True)
class ManagedEntry:
    logical_path: str
    kind: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ManagedManifest:
    resource_version: str
    entries: tuple[ManagedEntry, ...]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "resource_version": self.resource_version,
            "entries": [asdict(entry) for entry in self.entries],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> ManagedManifest:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            resource_version=str(raw["resource_version"]),
            entries=tuple(ManagedEntry(**entry) for entry in raw["entries"]),
        )
