# Claude Code Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 Codex-only Rules 生命周期管理器升级为支持 Codex/Claude 单选或多选、具有独立资源所有权和事务边界的元规范脚手架。

**Architecture:** Catalog v2 是 Rule、Skill、Agent 及调用关系的唯一真源；Adapter Registry 将同一选择规划为 Codex 或 Claude 的系统级/项目级 `ChangePlan`，现有 `FileTransaction` 负责所有写入。系统级 Base 使用 Adapter 独立 manifest，项目级 `.claude/CLAUDE.md` 与 Project Rule Extension 初始化后归项目所有。

**Tech Stack:** Python 3.11、Typer、PyYAML、Jinja2、jsonschema、platformdirs、pytest、Ruff、Pyright、Windows Claude Code 2.1.220+

## Global Constraints

- Rule 必须使用 `WHEN / MUST / MUST NOT`，Skill 承载执行细节，Agent 是委派执行对象。
- Catalog schema 固定为 v2；Rule Set schema 固定为 v2；不兼容旧 `adapter: codex`。
- `install` 只写系统级资源；`init` 只写项目级结构。
- 系统级 Base 可托管更新；项目指南、Project Rule Extension 和项目自有资源不得被覆盖或卸载。
- 不修改 `~/.claude/CLAUDE.md`、Claude/Codex settings、hooks、permissions 或业务代码。
- 每个 Adapter 使用独立 manifest、ChangePlan、授权、事务、回滚和卸载边界。
- Claude 系统级资源必须是普通文件，不依赖 symlink 或 junction。
- 自动测试不调用付费模型；真实 Claude CLI 行为单独记录人工验收。
- 代码与资源文件使用 English 标识；文档、交互说明和代码解释性注释使用简体中文。

---

## File Structure

### New files

- `src/project_execution_rules/adapters/__init__.py`：Adapter 注册表和公共查找入口。
- `src/project_execution_rules/adapters/base.py`：`Adapter` Protocol、`AdapterDetection`、`AdapterResourceSet`。
- `src/project_execution_rules/adapters/codex.py`：现有 Codex 用户/项目资源规划。
- `src/project_execution_rules/adapters/claude.py`：Claude 用户/项目资源规划和静态检查辅助。
- `src/project_execution_rules/selection.py`：Adapter/Catalog 选择归一化及引用闭包。
- `src/project_execution_rules/rulesets.py`：Rule Set v2 唯一解析/渲染入口。
- `src/project_execution_rules/resources/skills/<id>/SKILL.md`：Canonical Skill 正文。
- `src/project_execution_rules/resources/agents/rules-reviewer.md`：Canonical Agent 正文。
- `src/project_execution_rules/resources/adapters/claude/templates/CLAUDE.md.j2`：项目起始指南。
- `tests/test_adapters.py`：注册表、检测和 Adapter 资源规划。
- `tests/test_selection.py`：引用闭包和多 Adapter 可用性。
- `tests/test_rulesets.py`：Rule Set v2。
- `tests/test_claude_adapter.py`：Claude 资源布局、冲突和项目所有权。
- `test/integration/claude/TEST_CASES.md`：真实 Claude CLI 验收用例索引。

### Main modified files

- `src/project_execution_rules/models.py`：Adapter、Skill、Agent、Catalog、Rule Set v2 类型。
- `src/project_execution_rules/catalog.py`、`resources/catalog.yaml`、`resources/schemas/catalog.schema.json`：Catalog v2。
- `src/project_execution_rules/managed.py`、`paths.py`：manifest v2 和 Adapter 路径。
- `src/project_execution_rules/install.py`、`initialize.py`、`rendering.py`：委托 Adapter 规划。
- `src/project_execution_rules/lifecycle.py`：Adapter 独立 update/repair/uninstall/rollback。
- `src/project_execution_rules/checker.py`、`status.py`、`doctor.py`：多 Adapter 诊断。
- `src/project_execution_rules/cli.py`、`presentation.py`：可重复 `--adapter`、交互多选和分 Adapter 报告。
- `README.md`、`docs/CODEMAPS.md`、`AGENTS.md`、`src/project_execution_rules/AGENTS.md`、`pyproject.toml`：多 Adapter 文档与包描述。

---

### Task 1: Catalog v2 and Meta-Spec Resource Model

**Files:**
- Modify: `src/project_execution_rules/models.py:9-119`
- Modify: `src/project_execution_rules/catalog.py:23-143`
- Modify: `src/project_execution_rules/resources/catalog.yaml`
- Modify: `src/project_execution_rules/resources/schemas/catalog.schema.json`
- Modify: `src/project_execution_rules/resources/rules/**/*.md`
- Create: `src/project_execution_rules/resources/skills/*/SKILL.md`
- Create: `src/project_execution_rules/resources/agents/rules-reviewer.md`
- Test: `tests/test_models.py`
- Test: `tests/test_catalog.py`
- Test: `tests/test_resources.py`

**Interfaces:**
- Produces: `AdapterId`, `SkillInvocation`, `SkillDefinition`, `AgentDefinition`, extended `RuleDefinition.skills/agents`, `RuleCatalog.skills/agents`.
- Produces: `resolve_catalog_selection(catalog, rule_ids) -> CatalogSelection` in Task 2 consumes these models.

- [ ] **Step 1: Write failing model and Catalog tests**

```python
def test_catalog_v2_resolves_rule_dependencies() -> None:
    catalog = load_builtin_catalog()
    assert catalog.schema_version == 2
    assert catalog.rules["pull-request"].skills == ("pull-request",)
    assert "pull-request" in catalog.skills
    assert "rules-reviewer" in catalog.agents


def test_user_invocation_skill_cannot_be_preloaded() -> None:
    catalog = load_builtin_catalog()
    issues = validate_catalog_resources(catalog)
    assert not any(issue.code == "AGENT_SKILL_INVOCATION_INVALID" for issue in issues)
```

- [ ] **Step 2: Run focused tests and confirm v1 failures**

Run: `uv run pytest tests/test_models.py tests/test_catalog.py tests/test_resources.py -v`

Expected: FAIL because the new enums, fields and Catalog resources do not exist.

- [ ] **Step 3: Add exact v2 domain types**

Implement:

```python
class AdapterId(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"

class SkillInvocation(StrEnum):
    MODEL = "model"
    USER = "user"

@dataclass(frozen=True, slots=True)
class SkillDefinition:
    skill_id: str
    file: str
    invocation: SkillInvocation
    adapters: tuple[AdapterId, ...]

@dataclass(frozen=True, slots=True)
class AgentDefinition:
    agent_id: str
    file: str
    skills: tuple[str, ...]
    adapters: tuple[AdapterId, ...]
```

Extend `RuleDefinition` with `skills` and `agents`; extend `RuleCatalog` with `skills` and `agents`. Validate lowercase kebab-case IDs, missing dependencies, self-reference, unsupported Adapter dependencies and user-only Skill preloading.

- [ ] **Step 4: Convert Catalog/resources to v2**

Set `schema_version: 2`; declare Canonical Skills for task flows and governance commands, and `rules-reviewer` Agent. Rewrite Base Rules to preserve their existing clause IDs while presenting the stable sections:

```markdown
## WHEN
## MUST
## MUST NOT
```

Detailed procedural material moves to the referenced Canonical Skill. User-only governance Skills use `invocation: user`; Agent-preloaded Skills use `invocation: model`.

- [ ] **Step 5: Run Catalog and package resource tests**

Run: `uv run pytest tests/test_models.py tests/test_catalog.py tests/test_resources.py -v`

Expected: PASS; no Catalog structure issues, missing resources or invocation conflicts.

### Task 2: Adapter Protocol, Registry, Paths, and Selection Closure

**Files:**
- Create: `src/project_execution_rules/adapters/base.py`
- Create: `src/project_execution_rules/adapters/__init__.py`
- Create: `src/project_execution_rules/selection.py`
- Modify: `src/project_execution_rules/paths.py:8-35`
- Test: `tests/test_adapters.py`
- Test: `tests/test_selection.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: Task 1 Catalog models.
- Produces: `Adapter.plan_install`, `Adapter.plan_project_init`, `get_adapter`, `normalize_adapters`, `resolve_catalog_selection`.

- [ ] **Step 1: Write failing registry/path/closure tests**

```python
def test_registry_order_is_codex_then_claude() -> None:
    assert registered_adapter_ids() == (AdapterId.CODEX, AdapterId.CLAUDE)


def test_claude_paths_use_user_home(tmp_path: Path) -> None:
    paths = UserPaths.from_environment({}, tmp_path)
    assert paths.claude_rules == tmp_path / ".claude" / "rules"


def test_selection_adds_transitive_skill_and_agent_dependencies() -> None:
    selection = resolve_catalog_selection(load_builtin_catalog(), ("pull-request",))
    assert "pull-request" in selection.skills
    assert "rules-reviewer" in selection.agents
```

- [ ] **Step 2: Verify failures**

Run: `uv run pytest tests/test_adapters.py tests/test_selection.py tests/test_paths.py -v`

Expected: FAIL with missing modules/attributes.

- [ ] **Step 3: Implement minimal Protocol and immutable selection**

Use focused dataclasses:

```python
@dataclass(frozen=True, slots=True)
class AdapterDetection:
    adapter: AdapterId
    command: str
    available: bool

@dataclass(frozen=True, slots=True)
class CatalogSelection:
    rules: tuple[str, ...]
    skills: tuple[str, ...]
    agents: tuple[str, ...]

class Adapter(Protocol):
    id: AdapterId
    def detect(self, runner: CommandRunner) -> AdapterDetection: ...
    def plan_install(self, paths: UserPaths, catalog: RuleCatalog,
                     selection: CatalogSelection, *, allow_managed_drift: bool = False) -> ChangePlan: ...
    def plan_project_init(self, root: Path, facts: ProjectFacts,
                          selection: ProjectSelection, paths: UserPaths) -> ChangePlan: ...
```

Add `claude_home`, `claude_rules`, `claude_skills`, `claude_agents` and `manifest_path(adapter)` to `UserPaths`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_adapters.py tests/test_selection.py tests/test_paths.py -v`

Expected: PASS.

### Task 3: Adapter-Scoped Managed Manifest v2

**Files:**
- Modify: `src/project_execution_rules/managed.py:11-72`
- Modify: `src/project_execution_rules/install.py`
- Modify: `src/project_execution_rules/transactions.py`
- Test: `tests/test_install.py`
- Test: `tests/test_transactions.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: `AdapterId`, `CatalogSelection`, `UserPaths.manifest_path`.
- Produces: `ManagedManifest(schema_version, adapter, resource_version, selection, entries)` and Adapter-safe ownership checks.

- [ ] **Step 1: Write failing manifest tests**

```python
def test_manifest_round_trip_keeps_adapter_and_selection(tmp_path: Path) -> None:
    manifest = ManagedManifest(
        schema_version=2,
        adapter=AdapterId.CLAUDE,
        resource_version="1.0.0",
        selection=ManagedSelection(rules=("security",), skills=(), agents=()),
        entries=(ManagedEntry("rules/security.md", "rule", "0" * 64),),
    )
    manifest.save(tmp_path / "managed-user-claude.json")
    assert ManagedManifest.load(tmp_path / "managed-user-claude.json") == manifest
```

Add negative tests for wrong Adapter, absolute/`..` logical paths, duplicate entries, invalid SHA and manifest path mismatch.

- [ ] **Step 2: Verify failures**

Run: `uv run pytest tests/test_install.py tests/test_transactions.py -v`

Expected: FAIL on v1 manifest shape.

- [ ] **Step 3: Implement strict v2 schema and path-root ownership**

Serialize deterministic JSON with sorted selections and entries. `is_current_managed_file` receives the expected Adapter and Adapter Home; it rejects symlink/reparse targets and manifests whose `adapter` differs.

Transaction manifests gain optional required `adapter` for Adapter operations; rollback validates it before restoring.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_install.py tests/test_transactions.py -v`

Expected: PASS.

### Task 4: Codex Adapter Migration and Rule Set v2

**Files:**
- Create: `src/project_execution_rules/adapters/codex.py`
- Create: `src/project_execution_rules/rulesets.py`
- Modify: `src/project_execution_rules/install.py`
- Modify: `src/project_execution_rules/rendering.py`
- Modify: `src/project_execution_rules/initialize.py`
- Modify: `src/project_execution_rules/resources/templates/AGENTS.md.j2`
- Modify: `src/project_execution_rules/resources/templates/ruleset.yaml.j2`
- Test: `tests/test_rulesets.py`
- Test: `tests/test_install.py`
- Test: `tests/test_initialize.py`
- Test: `tests/test_checker.py`

**Interfaces:**
- Consumes: Adapter Protocol, manifest v2.
- Produces: `load_ruleset(path) -> RuleSet`, `render_ruleset(ruleset) -> str`, working `CodexAdapter`.

- [ ] **Step 1: Write failing Rule Set v2 and Codex regression tests**

```python
def test_ruleset_v2_supports_multiple_adapters() -> None:
    ruleset = load_ruleset_text("""schema_version: 2
rules_version: 1.0.0
adapters: [codex, claude]
profile: python
domains: {core: [security], profile: [python]}
overrides: {codex: [python], claude: []}
""")
    assert ruleset.adapters == (AdapterId.CODEX, AdapterId.CLAUDE)


def test_ruleset_v1_is_rejected() -> None:
    with pytest.raises(ProjectRulesError, match="RULESET_SCHEMA_INCOMPATIBLE"):
        load_ruleset_text("schema_version: 1\nadapter: codex\n")
```

Retain assertions for Codex `AGENTS.md`, Base symlinks, `.gitignore` and Override behavior under v2.

- [ ] **Step 2: Verify failures**

Run: `uv run pytest tests/test_rulesets.py tests/test_install.py tests/test_initialize.py tests/test_checker.py -v`

Expected: FAIL because v1 rendering is hard-coded.

- [ ] **Step 3: Move Codex resource planning behind `CodexAdapter`**

Port `_resource_changes`, installed Catalog rendering, Codex Agent/Skill layout, Base symlink planning and `AGENTS.md` rendering without changing behavior. Keep orchestration wrappers temporarily so existing call sites can migrate incrementally.

- [ ] **Step 4: Implement Rule Set v2 parser/renderer**

Enforce non-empty, deduplicated Registry-order Adapter list; Adapter-grouped Overrides; domains membership; exact schema version 2; no host paths or unknown keys.

- [ ] **Step 5: Run focused and Codex regression tests**

Run: `uv run pytest tests/test_rulesets.py tests/test_install.py tests/test_initialize.py tests/test_checker.py -v`

Expected: PASS with v2 fixtures.

### Task 5: Claude Adapter Global Resources

**Files:**
- Create: `src/project_execution_rules/adapters/claude.py`
- Create: `src/project_execution_rules/resources/adapters/claude/templates/rule.md.j2`
- Create: `src/project_execution_rules/resources/adapters/claude/templates/skill.md.j2`
- Create: `src/project_execution_rules/resources/adapters/claude/templates/agent.md.j2`
- Test: `tests/test_claude_adapter.py`
- Test: `tests/test_install.py`
- Test: `tests/test_resources.py`

**Interfaces:**
- Consumes: Catalog v2 selection and manifest v2.
- Produces: ordinary-file plans for `~/.claude/rules`, `skills/<id>/SKILL.md`, `agents/<id>.md`.

- [ ] **Step 1: Write failing Claude install tests**

Cover:

```python
def test_claude_install_plans_dependency_closure(tmp_path: Path) -> None:
    plan = adapter.plan_install(paths, catalog, selection)
    targets = {change.target for change in plan.changes}
    assert paths.claude_rules / "pull-request.md" in targets
    assert paths.claude_skills / "pull-request" / "SKILL.md" in targets
    assert paths.claude_agents / "rules-reviewer.md" in targets
    assert paths.home / ".claude" / "CLAUDE.md" not in targets
```

Also assert `paths` frontmatter, task/explicit skeleton, user-only Skill flag, Agent required `name/description/skills`, regular files only, deterministic output and non-managed conflict refusal.

- [ ] **Step 2: Verify failures**

Run: `uv run pytest tests/test_claude_adapter.py tests/test_install.py tests/test_resources.py -v`

Expected: FAIL because Claude Adapter/templates are absent.

- [ ] **Step 3: Implement Claude rendering and install planning**

Render all Rules, with native `paths` only for path rules; task/explicit Rules stay compact. Render Skills with `disable-model-invocation: true` only for `invocation: user`. Render Agents with required fields and only model-invocable preloaded Skills. Reuse the generic managed-plan builder so conflict/checksum behavior stays identical across Adapters.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_claude_adapter.py tests/test_install.py tests/test_resources.py -v`

Expected: PASS.

### Task 6: Claude Project Scaffold and Project Ownership

**Files:**
- Create: `src/project_execution_rules/resources/adapters/claude/templates/CLAUDE.md.j2`
- Modify: `src/project_execution_rules/adapters/claude.py`
- Modify: `src/project_execution_rules/initialize.py`
- Modify: `src/project_execution_rules/rendering.py`
- Test: `tests/test_claude_adapter.py`
- Test: `tests/test_initialize.py`
- Test: `tests/integration/test_windows_workflow.py`

**Interfaces:**
- Consumes: Rule Set v2 and `ProjectSelection.adapters`.
- Produces: `.claude/CLAUDE.md`, `<rule-id>.project.md`, optional empty local dirs, no Base copies.

- [ ] **Step 1: Write failing scaffold/ownership tests**

Test that init:

- refuses an Adapter without a matching global manifest/closure;
- creates `.claude/CLAUDE.md` only when absent;
- never overwrites an existing guide;
- creates only non-empty selected Project Rule Extensions;
- does not copy/link global Base into project `.claude`;
- treats absent empty `skills/agents` directories after clone as healthy;
- stages guide, Rule Set and Project Rule Extensions, not empty dirs.

- [ ] **Step 2: Verify failures**

Run: `uv run pytest tests/test_claude_adapter.py tests/test_initialize.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement Adapter-composed project plan**

`plan_project_init` validates global installations first, asks each selected Adapter for its project changes, adds one shared Rule Set change, deduplicates targets, and rejects cross-Adapter collisions. Symlink capability is required only when the Codex plan contains symlinks; Claude-only init must work without Developer Mode.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_claude_adapter.py tests/test_initialize.py tests/integration/test_windows_workflow.py -v`

Expected: PASS.

### Task 7: Multi-Adapter Checker, Status, and Doctor

**Files:**
- Modify: `src/project_execution_rules/checker.py`
- Modify: `src/project_execution_rules/status.py`
- Modify: `src/project_execution_rules/doctor.py`
- Modify: `src/project_execution_rules/commands.py`
- Test: `tests/test_checker.py`
- Test: `tests/test_doctor.py`
- Test: `tests/test_commands.py`

**Interfaces:**
- Consumes: Adapter Registry, Rule Set v2, manifest v2.
- Produces: Adapter-attributed `CheckIssue.evidence`, multi-Adapter status, `claude` CLI diagnostics.

- [ ] **Step 1: Write failing diagnostic tests**

Add cases for manifest drift isolation, missing global dependencies, malformed Claude frontmatter, user Skill shadowing, project Agent replacement warning, Project Rule Extension scope, missing empty dirs healthy, and `claude.cmd` command discovery.

- [ ] **Step 2: Verify failures**

Run: `uv run pytest tests/test_checker.py tests/test_doctor.py tests/test_commands.py -v`

Expected: FAIL.

- [ ] **Step 3: Split shared checks from Adapter checks**

`check_project` parses Rule Set once, runs Catalog/reference checks once, then invokes each Adapter project/global check. Every Adapter-specific issue contains `evidence={"adapter": adapter.id.value, ...}`. Status exposes `adapters` and per-Adapter issue counts.

Doctor probes `git`, `codex`, `claude`, and records executable/return code without reading credentials. `claude doctor` remains optional evidence, not a resource validator.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_checker.py tests/test_doctor.py tests/test_commands.py -v`

Expected: PASS.

### Task 8: Adapter-Scoped Lifecycle and Registry Impact Guard

**Files:**
- Modify: `src/project_execution_rules/lifecycle.py`
- Modify: `src/project_execution_rules/managed.py`
- Modify: `src/project_execution_rules/paths.py`
- Test: `tests/test_lifecycle.py`
- Test: `tests/test_transactions.py`
- Test: `tests/integration/test_windows_workflow.py`

**Interfaces:**
- Consumes: Adapter plans/manifests and project registry.
- Produces: per-Adapter update/repair/uninstall plans and Adapter-validated rollback.

- [ ] **Step 1: Write failing lifecycle tests**

Cover:

- Claude update never changes Codex manifest/resources;
- repair restores only managed global Base;
- repair does not overwrite guide/extensions/project Skills/Agents;
- rollback rejects Adapter mismatch;
- uninstall refuses while registered projects enable Adapter;
- `force=True` lists affected projects and deletes only managed global Base;
- multi-Adapter partial success is represented as separate reports.

- [ ] **Step 2: Verify failures**

Run: `uv run pytest tests/test_lifecycle.py tests/test_transactions.py -v`

Expected: FAIL on single-manifest assumptions.

- [ ] **Step 3: Implement Adapter-scoped lifecycle plans**

Replace global `managed-user.json` usage with `paths.manifest_path(adapter)`. Add Adapter to transaction metadata and validation. Scan accessible registered projects before update/uninstall; default uninstall rejects active references, force preserves all project files.

- [ ] **Step 4: Run lifecycle and Windows tests**

Run: `uv run pytest tests/test_lifecycle.py tests/test_transactions.py tests/integration/test_windows_workflow.py -v`

Expected: PASS.

### Task 9: CLI Multi-Select, Automation, and Result Reporting

**Files:**
- Modify: `src/project_execution_rules/cli.py`
- Modify: `src/project_execution_rules/presentation.py`
- Modify: `src/project_execution_rules/commands.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: Registry/detection and Adapter-scoped application functions.
- Produces: repeatable `--adapter`, interactive multi-select, deterministic JSON arrays and partial-success output.

- [ ] **Step 1: Write failing CLI tests**

Use `CliRunner` to verify:

- repeated `--adapter codex --adapter claude`;
- duplicate normalization and Registry ordering;
- install auto-detects one/both CLIs;
- non-interactive install with neither CLI fails unless Adapter explicit;
- init only offers installed Adapters and defaults to all installed in non-interactive mode;
- JSON write commands still require `--yes` unless dry-run;
- output groups plans/reports by Adapter;
- uninstall active-project guard and `--force`.

- [ ] **Step 2: Verify failures**

Run: `uv run pytest tests/test_cli.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement shared Adapter selection helper**

Use one helper for all commands; do not duplicate detection policy. Keep current command names and exit-code classes. `init` must no longer create/install user resources. Multi-Adapter writes execute independent transactions and report partial success faithfully.

- [ ] **Step 4: Run CLI tests**

Run: `uv run pytest tests/test_cli.py -v`

Expected: PASS.

### Task 10: Documentation, Packaging, Full Verification, and Manual Acceptance Assets

**Files:**
- Modify: `README.md`
- Modify: `docs/CODEMAPS.md`
- Modify: `AGENTS.md`
- Modify: `src/project_execution_rules/AGENTS.md`
- Modify: `pyproject.toml`
- Modify: `test/README.md` if present; otherwise create project-level test index consistent with repository conventions.
- Create: `test/integration/claude/TEST_CASES.md`
- Create: `test/integration/claude/evidence/2026-07-27_claude_adapter_acceptance/README.md`
- Test: all tests

**Interfaces:**
- Consumes: complete implementation.
- Produces: published resource package, accurate docs, repeatable manual acceptance instructions.

- [ ] **Step 1: Add package/resource assertions**

Extend `tests/test_resources.py` to assert wheel-visible Canonical Rules/Skills/Agents and both Adapter resources. Verify project metadata describes Codex and Claude rather than Codex-only.

- [ ] **Step 2: Update user and architecture documentation**

Document install/init separation, repeated Adapter options, Rule/Skill/Agent responsibilities, global/project ownership, destructive Rule Set v2 boundary, uninstall guard, Claude Code 2.1.220+ and manual `/context`/`/skills` workflow.

- [ ] **Step 3: Create manual acceptance case and evidence template**

Record exact prerequisites, fixed prompts, three-run behavior threshold, static discovery checks and evidence filenames. Do not claim a real CLI run occurred until its raw evidence is present.

- [ ] **Step 4: Run format, type, unit, integration, and build verification**

Run:

```bash
uv run ruff check .
uv run pyright
uv run pytest -v
uv build
python -c "import zipfile, pathlib; p=next(pathlib.Path('dist').glob('*.whl')); z=zipfile.ZipFile(p); names=z.namelist(); assert any('/adapters/claude/' in n for n in names); assert any('/skills/' in n for n in names); assert any('/agents/' in n for n in names)"
```

Expected: all commands exit 0; full suite passes; wheel contains Claude Adapter and Canonical resources.

- [ ] **Step 5: Run non-paid local CLI smoke checks**

Run:

```bash
uv run project-rules install --adapter claude --dry-run --format json
uv run project-rules doctor --format json
```

Expected: valid JSON, no writes during dry-run, Claude 2.1.220+ detected when installed. If authentication or interactive `/context` evidence is unavailable, record the manual acceptance step as not executed rather than claiming success.

---

## Plan Self-Review

- Spec coverage: Tasks 1–10 cover Catalog v2, Rule/Skill/Agent resources, Adapter Protocol, Rule Set v2, manifests, Claude global/project resources, CLI, lifecycle, Checker/Doctor, packaging, docs and real CLI acceptance assets.
- Ownership: Tasks 6 and 8 explicitly prevent update/repair/uninstall from modifying project-owned content.
- Claude mechanics: Tasks 1, 5 and 6 separate user-only Skills from Agent-preloaded Skills and treat Rule Brief as generated guidance rather than hard interception.
- Type consistency: `AdapterId`, `CatalogSelection`, `ManagedManifest`, `RuleSet` and Adapter method names are introduced before downstream tasks consume them.
- Scope: No task generates target-project tests/CI/business files or hooks/permissions.
- No implementation placeholders remain; manual behavior verification is clearly separated from deterministic tests.
