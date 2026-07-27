from __future__ import annotations

import pytest

from project_execution_rules.yaml_utils import (
    as_int,
    as_mapping,
    as_object_tuple,
    as_string,
    as_string_tuple,
    load_mapping,
)


def test_load_mapping_returns_typed_top_level_mapping() -> None:
    assert load_mapping("name: sample\n") == {"name": "sample"}


def test_load_mapping_rejects_sequence() -> None:
    with pytest.raises(ValueError, match="mapping"):
        load_mapping("- item\n")


def test_nested_helpers_validate_values() -> None:
    assert as_mapping({"items": ["a"]}) == {"items": ["a"]}
    assert as_object_tuple([{"name": "a"}]) == ({"name": "a"},)
    assert as_int(1) == 1
    assert as_string("value") == "value"
    assert as_string_tuple(["a", "b"]) == ("a", "b")

    with pytest.raises(ValueError, match="strings"):
        as_string_tuple(["a", 1])
