from __future__ import annotations

from project_execution_rules.yaml_utils import load_mapping


def parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Parse optional YAML frontmatter without interpreting the Markdown body."""
    if not text.startswith("---\n"):
        return {}, text.lstrip()
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("frontmatter is not terminated")
    raw = text[4:end]
    return load_mapping(raw or "{}", name="frontmatter"), text[end + 5 :].lstrip()
