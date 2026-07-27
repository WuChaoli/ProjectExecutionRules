from __future__ import annotations

from project_execution_rules.catalog import load_builtin_catalog
from project_execution_rules.models import ActivationType


def test_builtin_catalog_contains_core_and_python_profile() -> None:
    catalog = load_builtin_catalog()

    assert len([rule for rule in catalog.rules.values() if rule.core]) == 13
    assert catalog.profiles["python"] == ("python",)
    assert catalog.rules["python"].activation is ActivationType.PATHS


def test_task_and_explicit_rules_are_not_path_scoped() -> None:
    catalog = load_builtin_catalog()

    assert catalog.rules["git"].activation is ActivationType.TASK
    assert catalog.rules["git"].paths == ()
    assert catalog.rules["harness"].activation is ActivationType.EXPLICIT
    assert catalog.rules["harness"].paths == ()
