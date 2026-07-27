from __future__ import annotations

import yaml

from project_execution_rules.catalog import load_builtin_catalog
from project_execution_rules.detection import ProjectFacts
from project_execution_rules.initialize import ProjectSelection
from project_execution_rules.models import ActivationType, RuleDefinition

_EXPLICIT_ENTRIES = {
    "agent-governance": "Codex Skill `$agent-governance`",
    "tool-governance": "Codex Skill `$tool-governance`",
    "rules-review": (
        "首选 CLI `project-rules review`；Codex Agent/Skill `rules-reviewer` "
        "是同一 Schema 的交互适配器"
    ),
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
- 禁止读取或提交 `.env`、密钥、令牌及其他凭据。
- 日志、Trace、指标、PID 和本机运行状态只在当前任务明确授权的诊断或可观测场景
  中最小读取；必须排除无关文件并对输出脱敏。
- 外部副作用和超出项目范围的写入必须获得明确授权。

## Rules 读取

- Catalog 是 Rule、Profile 和 Trigger 的唯一事实来源；AGENTS 路由与 Markdown
  frontmatter 是派生视图，由 `project-rules check` 检查漂移。
- paths 使用仓库相对 POSIX 路径、`/` 分隔、区分大小写并采用 `**` Glob；task 与
  explicit 只匹配 Catalog 中的精确 canonical token，不隐式接受别名。自然语言
  只能在意图唯一时映射；否则列出候选并停止。
- 先读取 `.rules/<domain>-rules.md`，再读取存在的
  `.rules/<domain>-rules.override.md`。
- Security Rule 始终加载；普通任务首次再选择最多两个直接相关领域，之后按当前阶段
  增量加载。Rule 预算按完整 Markdown 的 UTF-8 bytes 计量，包含 frontmatter、
  Base 和 Override，不包含单独受 8 KiB 限制的 AGENTS；首次及会话累计硬上限均为
  24 KiB。达到上限后不得加载更多 Rule。
- 显式 Trigger 命中时只加载 Security 和对应 explicit 领域。没有显式命中时，合并
  所有精确命中的 task 与 paths 候选；候选不超过两个则全部加载，超过两个必须列出
  全部候选并停止，不按“最直接”或隐含优先级丢弃领域。
- Base 是完整基线；Override 必须声明 `override_schema` 和结构化 `operations`。
  `add_constraint` 使用 `<PREFIX>-OVR-<NNN>` 并指向一个 Base Rule ID；
  `narrow_paths` 指向当前领域。Override 不得替换 Base ID、扩大 Trigger 或削弱
  Security Rule；任何矛盾、未知目标或无法机械判定的冲突都必须拒绝，不猜测
  “更严格”的一侧。
- `project-rules check` 验证 Base 链接目标、用户级 manifest checksum、Trigger、
  AGENTS 路由、Override 和内容预算。
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
    operations: list[dict[str, str]] = []
    index = 1
    if facts.python_requirement:
        rule_id = f"PY-OVR-{index:03d}"
        operations.append({"id": rule_id, "operation": "add_constraint", "target": "PY-001"})
        lines.append(f"- `{rule_id}`：项目 Python 版本要求为 `{facts.python_requirement}`。")
        index += 1
    if facts.package_manager != "unknown":
        rule_id = f"PY-OVR-{index:03d}"
        operations.append({"id": rule_id, "operation": "add_constraint", "target": "PY-003"})
        lines.append(f"- `{rule_id}`：依赖和命令统一使用 `{facts.package_manager}`。")
        index += 1
    if facts.source_dirs:
        rule_id = f"PY-OVR-{index:03d}"
        operations.append({"id": rule_id, "operation": "add_constraint", "target": "PY-006"})
        joined = "、".join(f"`{item}/`" for item in facts.source_dirs)
        lines.append(f"- `{rule_id}`：项目源码入口为 {joined}。")
    metadata = yaml.safe_dump(
        {"override_schema": 1, "operations": operations},
        allow_unicode=True,
        sort_keys=False,
    ).rstrip()
    return f"---\n{metadata}\n---\n\n" + "\n".join(lines).rstrip() + "\n"
