from __future__ import annotations

from project_execution_rules.catalog import load_builtin_catalog
from project_execution_rules.detection import ProjectFacts
from project_execution_rules.initialize import ProjectSelection
from project_execution_rules.models import ActivationType, RuleDefinition

_EXPLICIT_ENTRIES = {
    "agent-governance": "Codex Skill `$agent-governance`",
    "tool-governance": "Codex Skill `$tool-governance`",
    "rules-review": "Codex Agent/Skill `rules-reviewer`，CLI `project-rules review`",
}


def route_label(domain: str, definition: RuleDefinition) -> str:
    if definition.activation is ActivationType.ALWAYS:
        return "始终加载"
    if definition.activation is ActivationType.PATHS:
        return f"路径：{'、'.join(definition.paths)}"
    if definition.activation is ActivationType.TASK:
        return f"{domain.replace('-', ' ').title()} 任务：{'、'.join(definition.tasks)}"
    entries = "；".join(
        f"`{command}` -> {_EXPLICIT_ENTRIES[command]}" for command in definition.commands
    )
    return f"显式入口：{entries}"


def route_row(domain: str, definition: RuleDefinition) -> str:
    return f"| {route_label(domain, definition)} | `.rules/{domain}-rules.md` |"


def render_agents(selection: ProjectSelection) -> str:
    catalog = load_builtin_catalog()
    domains = selection.core_domains + ("python",)
    rows = "\n".join(route_row(domain, catalog.rules[domain]) for domain in domains)
    paths = "\n".join(f"- `.rules/{domain}-rules.md`" for domain in domains)
    return f"""# Project Rules Router

## 事实来源与安全内核

- 当前行为以项目源码、测试、项目元数据、锁文件和 CI 配置为准。
- 不读取或提交 `.env`、凭据、PID、日志和本机运行状态。
- 外部副作用和超出项目范围的写入必须获得明确授权。

## Rules 读取

- 先读取 `.rules/<domain>-rules.md`，再读取存在的
  `.rules/<domain>-rules.override.md`。
- 首次最多选择两个直接相关领域，之后按当前阶段增量加载。
- Rules 缺失时明确报告，不自动生成或绕过。

## 领域路由

| 触发条件 | Rule |
|---|---|
{rows}

## Rule 入口

{paths}
"""


def render_ruleset(selection: ProjectSelection) -> str:
    catalog = load_builtin_catalog()
    core = "\n".join(f"    - {domain}" for domain in selection.core_domains)
    overrides = "\n".join(f"  - {domain}" for domain in selection.override_domains)
    return f"""schema_version: 1
rules_version: {catalog.rules_version}
adapter: codex
profile: python

domains:
  core:
{core}
  profile:
    - python

overrides:
{overrides if overrides else "  []"}
"""


def render_python_override(facts: ProjectFacts) -> str:
    lines = ["# Python Rule Overrides", ""]
    index = 1
    if facts.python_requirement:
        lines.append(
            f"- `PY-OVR-{index:03d}`：项目 Python 版本要求为 `{facts.python_requirement}`。"
        )
        index += 1
    if facts.package_manager != "unknown":
        lines.append(f"- `PY-OVR-{index:03d}`：依赖和命令统一使用 `{facts.package_manager}`。")
        index += 1
    if facts.source_dirs:
        joined = "、".join(f"`{item}/`" for item in facts.source_dirs)
        lines.append(f"- `PY-OVR-{index:03d}`：项目源码入口为 {joined}。")
    return "\n".join(lines).rstrip() + "\n"
