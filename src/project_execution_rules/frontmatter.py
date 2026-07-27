from __future__ import annotations

from typing import Any

import yaml


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse optional YAML frontmatter without interpreting the Markdown body."""
    if not text.startswith("---\n"):
        return {}, text.lstrip()
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("frontmatter is not terminated")
    raw = text[4:end]
    loaded = yaml.safe_load(raw) or {}
    if not isinstance(loaded, dict):
        raise ValueError("frontmatter must be a mapping")
    return dict(loaded), text[end + 5 :].lstrip()
