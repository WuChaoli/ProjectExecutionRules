from __future__ import annotations

from pathlib import Path

import pytest

from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.models import AdapterId, RuleSet
from project_execution_rules.rulesets import (
    load_ruleset,
    load_ruleset_text,
    render_ruleset,
)

_VALID_RULESET = """schema_version: 2
rules_version: 1.0.0
adapters:
  - codex
  - claude
profile: python
domains:
  core:
    - security
  profile:
    - python
overrides:
  codex:
    - python
  claude: []
"""


def test_ruleset_v2_supports_multiple_adapters() -> None:
    ruleset = load_ruleset_text(_VALID_RULESET)

    assert ruleset.adapters == (AdapterId.CODEX, AdapterId.CLAUDE)
    assert ruleset.overrides == {
        AdapterId.CODEX: ("python",),
        AdapterId.CLAUDE: (),
    }


def test_load_ruleset_reads_v2_file(tmp_path: Path) -> None:
    path = tmp_path / "ruleset.yaml"
    path.write_text(_VALID_RULESET, encoding="utf-8")

    assert load_ruleset(path).profile == "python"


def test_ruleset_v1_is_rejected_as_incompatible() -> None:
    with pytest.raises(ProjectRulesError, match="RULESET_SCHEMA_INCOMPATIBLE") as captured:
        load_ruleset_text("schema_version: 1\nadapter: codex\n")

    assert captured.value.code == "RULESET_SCHEMA_INCOMPATIBLE"


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ("adapters: []", "non-empty"),
        ("adapters: [codex, codex]", "duplicate"),
        ("adapters: [claude, codex]", "Registry order"),
    ],
)
def test_ruleset_rejects_invalid_adapter_lists(replacement: str, message: str) -> None:
    text = _VALID_RULESET.replace("adapters:\n  - codex\n  - claude", replacement)

    with pytest.raises(ProjectRulesError, match=message):
        load_ruleset_text(text)


def test_ruleset_rejects_override_outside_selected_domains() -> None:
    text = _VALID_RULESET.replace("    - python\n  claude", "    - testing\n  claude")

    with pytest.raises(ProjectRulesError, match="selected domain"):
        load_ruleset_text(text)


def test_ruleset_rejects_unknown_domain_membership() -> None:
    text = _VALID_RULESET.replace("    - security", "    - unknown")

    with pytest.raises(ProjectRulesError, match="unknown Rule domain"):
        load_ruleset_text(text)


def test_ruleset_rejects_profile_rule_in_core_domains() -> None:
    text = _VALID_RULESET.replace("    - security", "    - python", 1).replace(
        "  profile:\n    - python", "  profile: []"
    )

    with pytest.raises(ProjectRulesError, match="domains.core"):
        load_ruleset_text(text)


def test_ruleset_rejects_core_rule_in_profile_domains() -> None:
    text = _VALID_RULESET.replace("  core:\n    - security", "  core: []").replace(
        "  profile:\n    - python", "  profile:\n    - security"
    ).replace("    - python\n  claude", "    - security\n  claude")

    with pytest.raises(ProjectRulesError, match="domains.profile"):
        load_ruleset_text(text)


def test_ruleset_rejects_unknown_and_host_path_fields() -> None:
    with pytest.raises(ProjectRulesError, match="unknown keys"):
        load_ruleset_text(_VALID_RULESET + "home: C:/Users/example\n")


def test_ruleset_renderer_uses_v2_grouped_overrides() -> None:
    rendered = render_ruleset(
        RuleSet(
            schema_version=2,
            rules_version="1.0.0",
            adapters=(AdapterId.CODEX, AdapterId.CLAUDE),
            profile="python",
            core_domains=("security",),
            profile_domains=("python",),
            overrides={AdapterId.CODEX: ("python",), AdapterId.CLAUDE: ()},
        )
    )

    assert load_ruleset_text(rendered) == RuleSet(
        schema_version=2,
        rules_version="1.0.0",
        adapters=(AdapterId.CODEX, AdapterId.CLAUDE),
        profile="python",
        core_domains=("security",),
        profile_domains=("python",),
        overrides={AdapterId.CODEX: ("python",), AdapterId.CLAUDE: ()},
    )
