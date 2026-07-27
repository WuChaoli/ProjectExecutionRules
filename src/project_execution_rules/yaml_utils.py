from __future__ import annotations

from typing import cast

import yaml


def as_string(value: object, *, name: str = "value") -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def as_int(value: object, *, name: str = "value") -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


def as_mapping(value: object, *, name: str = "value") -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    raw = cast(dict[object, object], value)
    result: dict[str, object] = {}
    for key, item in raw.items():
        if not isinstance(key, str):
            raise ValueError(f"{name} keys must be strings")
        result[key] = item
    return result


def as_string_tuple(value: object, *, name: str = "value") -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        raise ValueError(f"{name} must contain strings")
    raw = cast(list[object] | tuple[object, ...], value)
    result: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(f"{name} must contain strings")
        result.append(item)
    return tuple(result)


def as_object_tuple(value: object, *, name: str = "value") -> tuple[object, ...]:
    if not isinstance(value, list | tuple):
        raise ValueError(f"{name} must be a sequence")
    return tuple(cast(list[object] | tuple[object, ...], value))


def load_mapping(text: str, *, name: str = "YAML document") -> dict[str, object]:
    try:
        loaded = cast(object, yaml.safe_load(text))
    except yaml.YAMLError as error:
        raise ValueError(f"{name} contains invalid YAML: {error}") from error
    return as_mapping(loaded, name=name)
