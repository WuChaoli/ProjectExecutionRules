from __future__ import annotations

from project_execution_rules.catalog import (
    load_builtin_catalog,
    validate_catalog_resources,
)
from project_execution_rules.frontmatter import parse_frontmatter


def test_parse_frontmatter_separates_metadata_and_body() -> None:
    metadata, body = parse_frontmatter('---\npaths:\n  - "**/*.py"\n---\n\n# Python Rules\n')

    assert metadata == {"paths": ["**/*.py"]}
    assert body.startswith("# Python Rules")


def test_builtin_catalog_resources_are_consistent() -> None:
    issues = validate_catalog_resources(load_builtin_catalog())

    assert issues == ()
