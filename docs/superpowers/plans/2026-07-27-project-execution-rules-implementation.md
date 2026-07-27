# Project Execution Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个可通过 `uv tool` 安装、默认交互式、可离线管理 Codex CLI Rules 生命周期的 Windows Python CLI。

**Architecture:** 使用模块化单体 Python 包，内置 Core Rules、Python Profile、Codex Adapter 和 JSON Schema。命令层只负责输入输出，领域层负责 Catalog、Rule Set、触发器、预算、状态与事务，文件系统写入全部通过可恢复事务完成。

**Tech Stack:** Python 3.11、uv、Typer、Rich、PyYAML、platformdirs、pytest、Ruff、Pyright。

## Global Constraints

- 首版只支持单用户、单项目、本地 Windows、Codex CLI 和完整 Python Profile。
- CLI 使用 Python 实现，但 Rule/Profile/Adapter 接口不得绑定 Python 项目。
- 所有 Rule、模板、Agent、Skill 和 Schema 作为 package resources 内置，运行时不得从网络下载。
- 用户级 Rule Home 为 `%USERPROFILE%\.agents\rules\`，项目目录为 `.rules/`。
- Base 文件名为 `<domain>-rules.md`，项目覆盖为 `<domain>-rules.override.md`。
- Override 必须是 Git 跟踪的普通文件，不存在真实差异时不得创建。
- 路径触发使用 Claude Code 兼容的顶层 YAML `paths` frontmatter。
- CLI 只治理 Rules，不审计业务功能，不运行项目测试、构建或外部服务，不修改业务代码。
- `.codex/config.toml` 只检查并建议，不自动修改。
- 用户级和项目级变更分别计划、授权、备份、写入、验证和回滚。
- 项目 `AGENTS.md` 软上限 6 KiB、硬上限 8 KiB；Base Rule 4/8 KiB；Override 2/4 KiB；普通任务首次加载 16/24 KiB。
- 所有实现任务使用 TDD；每个任务提交前运行目标测试和 `git diff --check`。

---

### Task 1：建立可安装包和领域模型

**Files:**
- Create: `pyproject.toml`
- Create: `src/project_execution_rules/__init__.py`
- Create: `src/project_execution_rules/models.py`
- Create: `src/project_execution_rules/errors.py`
- Create: `tests/test_models.py`

**Interfaces:**
- Produces: `ActivationType`、`RuleDefinition`、`RuleCatalog`、`RuleSet`、`CheckIssue`、`CheckReport`、`ProjectState`、`OutputFormat`。
- Produces: `ProjectRulesError(code, message, evidence, remediation, exit_code)`。

- [ ] **Step 1: Write failing model tests**

```python
def test_rule_definition_rejects_parent_path():
    with pytest.raises(ValueError, match="project-relative"):
        RuleDefinition(
            domain="python",
            file="profiles/python/python-rules.md",
            activation=ActivationType.PATHS,
            paths=("../secret",),
        )


def test_check_report_serializes_stable_json():
    report = CheckReport(state=ProjectState.HEALTHY, issues=())
    assert report.to_dict() == {"state": "healthy", "issues": []}
```

- [ ] **Step 2: Run the model tests and confirm they fail**

Run: `uv run pytest tests/test_models.py -q`

Expected: collection fails because `project_execution_rules.models` does not exist.

- [ ] **Step 3: Create package metadata and immutable dataclasses**

Use Python 3.11, expose `project-rules = "project_execution_rules.cli:app"`, include package data, and implement enum-backed frozen dataclasses with explicit `to_dict()` methods. Error JSON fields are always `code`、`message`、`evidence`、`remediation`。

- [ ] **Step 4: Run model tests and static gates**

Run:

```powershell
uv sync
uv run pytest tests/test_models.py -q
uv run ruff check src tests
```

Expected: tests and Ruff pass.

- [ ] **Step 5: Commit**

```powershell
git add -- pyproject.toml uv.lock src tests/test_models.py
git commit -m "构建：建立CLI包与领域模型"
```

### Task 2：实现内置 Rule Catalog、触发器和资源校验

**Files:**
- Create: `src/project_execution_rules/catalog.py`
- Create: `src/project_execution_rules/frontmatter.py`
- Create: `src/project_execution_rules/resources/catalog.yaml`
- Create: `src/project_execution_rules/resources/rules/core/*.md`
- Create: `src/project_execution_rules/resources/rules/profiles/python/python-rules.md`
- Create: `src/project_execution_rules/resources/schemas/catalog.schema.json`
- Create: `tests/test_catalog.py`
- Create: `tests/test_resources.py`

**Interfaces:**
- Consumes: Task 1 models and errors.
- Produces: `load_builtin_catalog() -> RuleCatalog`。
- Produces: `parse_frontmatter(text: str) -> tuple[dict[str, object], str]`。
- Produces: `validate_catalog_resources(catalog: RuleCatalog) -> tuple[CheckIssue, ...]`。

- [ ] **Step 1: Write failing Catalog tests**

```python
def test_builtin_catalog_contains_core_and_python_profile():
    catalog = load_builtin_catalog()
    assert "security" in catalog.rules
    assert catalog.profiles["python"] == ("python",)


def test_python_paths_match_frontmatter():
    report = validate_catalog_resources(load_builtin_catalog())
    assert not report
```

- [ ] **Step 2: Run tests and confirm missing implementations**

Run: `uv run pytest tests/test_catalog.py tests/test_resources.py -q`

Expected: import failure for Catalog functions.

- [ ] **Step 3: Implement Catalog parsing and resources**

Catalog contains thirteen Core domains and Python Profile. Each Rule uses stable IDs and the body sections `事实来源`、`执行规则`、`验证要求`、`职责边界`。Python Rule frontmatter covers `**/*.py`、`pyproject.toml` and supported lock files. Task/explicit Rules do not contain empty `paths`。

- [ ] **Step 4: Validate IDs, triggers, frontmatter and budgets**

Reject duplicate IDs, unsupported prefixes, absolute paths, parent traversal, empty path sets, Catalog/frontmatter drift, Base files above 8 KiB and startup Rule total above 24 KiB.

- [ ] **Step 5: Run tests**

Run:

```powershell
uv run pytest tests/test_catalog.py tests/test_resources.py -q
uv run ruff check src tests
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add -- src/project_execution_rules/catalog.py src/project_execution_rules/frontmatter.py src/project_execution_rules/resources tests/test_catalog.py tests/test_resources.py
git commit -m "规则：内置Core与Python规则目录"
```

### Task 3：实现 Windows 路径、托管清单和可恢复事务

**Files:**
- Create: `src/project_execution_rules/paths.py`
- Create: `src/project_execution_rules/managed.py`
- Create: `src/project_execution_rules/transactions.py`
- Create: `tests/test_paths.py`
- Create: `tests/test_transactions.py`

**Interfaces:**
- Produces: `UserPaths.from_environment(environ, home) -> UserPaths`。
- Produces: `ManagedManifest.load/save`，记录 logical path、resource version、SHA-256，不记录凭据或文件正文。
- Produces: `FileTransaction.plan_write()`、`plan_symlink()`、`plan_remove()`、`apply()`、`restore()`、`cleanup()`。

- [ ] **Step 1: Write failing Windows path and rollback tests**

```python
def test_user_paths_use_local_app_data(tmp_path):
    paths = UserPaths.from_environment(
        {"LOCALAPPDATA": str(tmp_path / "local")},
        tmp_path / "home",
    )
    assert paths.state_home == tmp_path / "local" / "ProjectExecutionRules"


def test_failed_verification_restores_original(tmp_path):
    target = tmp_path / "AGENTS.md"
    target.write_text("original", encoding="utf-8")
    transaction = FileTransaction(tmp_path / "state", tmp_path)
    transaction.plan_write(target, b"changed")
    with pytest.raises(TransactionError):
        transaction.apply(lambda: False)
    assert target.read_text(encoding="utf-8") == "original"
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest tests/test_paths.py tests/test_transactions.py -q`

- [ ] **Step 3: Implement explicit-path transaction engine**

Every target is resolved and checked against the exact authorized root before mutation. Recursive deletion is not used. Backups are content-addressed inside `%LOCALAPPDATA%\ProjectExecutionRules\backups\<transaction-id>`，manifest uses relative logical paths。

- [ ] **Step 4: Add failure tests**

Cover non-managed conflict, target outside root, symlink target mismatch, interrupted transaction, successful restore, failed restore preserving backup and cleanup refusing unverified state.

- [ ] **Step 5: Run tests and commit**

Run: `uv run pytest tests/test_paths.py tests/test_transactions.py -q`

```powershell
git add -- src/project_execution_rules/paths.py src/project_execution_rules/managed.py src/project_execution_rules/transactions.py tests/test_paths.py tests/test_transactions.py
git commit -m "基础设施：实现受控文件事务"
```

### Task 4：实现用户级安装与 Doctor

**Files:**
- Create: `src/project_execution_rules/install.py`
- Create: `src/project_execution_rules/doctor.py`
- Create: `src/project_execution_rules/resources/adapters/codex/agents/rules-reviewer.toml`
- Create: `src/project_execution_rules/resources/adapters/codex/skills/rules-reviewer/SKILL.md`
- Create: `tests/test_install.py`
- Create: `tests/test_doctor.py`

**Interfaces:**
- Produces: `plan_user_install(paths, catalog, version) -> ChangePlan`。
- Produces: `install_user_resources(plan, confirm) -> OperationReport`。
- Produces: `run_doctor(root, paths, command_runner) -> CheckReport`。

- [ ] **Step 1: Write failing install/doctor tests**

Verify dry-run has no writes, install creates canonical Rules and managed manifest, non-managed conflicts stop, doctor reports missing Codex/Git and does not run pytest/build commands.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest tests/test_install.py tests/test_doctor.py -q`

- [ ] **Step 3: Implement installation and non-destructive probes**

Doctor may run `codex --version`、`git --version` and a temporary symlink probe. It must never run commands extracted from Markdown or project quality commands. `.codex/config.toml` is inspected only for existence and reported as advisory; its contents are not rewritten.

- [ ] **Step 4: Run tests and commit**

Run: `uv run pytest tests/test_install.py tests/test_doctor.py -q`

```powershell
git add -- src/project_execution_rules/install.py src/project_execution_rules/doctor.py src/project_execution_rules/resources/adapters tests/test_install.py tests/test_doctor.py
git commit -m "功能：安装Codex规则资源并诊断环境"
```

### Task 5：实现 Python 项目探测与初始化

**Files:**
- Create: `src/project_execution_rules/detection.py`
- Create: `src/project_execution_rules/initialize.py`
- Create: `src/project_execution_rules/rendering.py`
- Create: `src/project_execution_rules/resources/templates/AGENTS.md.j2`
- Create: `src/project_execution_rules/resources/templates/ruleset.yaml.j2`
- Create: `tests/test_detection.py`
- Create: `tests/test_initialize.py`

**Interfaces:**
- Produces: `detect_project(root: Path) -> ProjectFacts`。
- Produces: `plan_project_init(root, facts, selection, user_paths) -> ChangePlan`。
- Produces: `initialize_project(plan, confirm) -> OperationReport`。

- [ ] **Step 1: Write failing detection/init tests**

Create fixtures for `pyproject.toml` with uv、Poetry and generic projects. Verify recommended Python Profile, discovered lock files, minimal AGENTS routing, exact base links, no empty Override, exact `.gitignore` entries and tracked `ruleset.yaml`。

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest tests/test_detection.py tests/test_initialize.py -q`

- [ ] **Step 3: Implement fact detection without executing project commands**

Read only project metadata, filenames, Git metadata and CI paths. Do not read `.env` or logs. `pyproject.toml` is parsed with `tomllib`。

- [ ] **Step 4: Implement deterministic rendering**

AGENTS contains source-of-truth, safety kernel, Base then Override loading order, task routes and minimal navigation. Project initialization requires Git and verified user installation; Base is symlinked, Override is created only for selected real differences.

- [ ] **Step 5: Run tests and commit**

Run: `uv run pytest tests/test_detection.py tests/test_initialize.py -q`

```powershell
git add -- src/project_execution_rules/detection.py src/project_execution_rules/initialize.py src/project_execution_rules/rendering.py src/project_execution_rules/resources/templates tests/test_detection.py tests/test_initialize.py
git commit -m "功能：初始化Python项目规则集"
```

### Task 6：实现 Check、Status 和 Rules Review

**Files:**
- Create: `src/project_execution_rules/checker.py`
- Create: `src/project_execution_rules/status.py`
- Create: `src/project_execution_rules/reviewer.py`
- Create: `src/project_execution_rules/resources/schemas/review-report.schema.json`
- Create: `tests/test_checker.py`
- Create: `tests/test_reviewer.py`

**Interfaces:**
- Produces: `check_project(root, paths) -> CheckReport`。
- Produces: `get_project_status(root, paths) -> StatusReport`。
- Produces: `review_rules(root, paths, runner) -> ReviewReport`。

- [ ] **Step 1: Write failing fixture tests**

Cover healthy、missing link、wrong target、untracked Override、duplicate ID、Catalog/frontmatter drift、budget overflow、route gap、update available and incompatible schema。

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest tests/test_checker.py tests/test_reviewer.py -q`

- [ ] **Step 3: Implement deterministic checker and status**

Checker only reads Rules infrastructure and Git index. It must not inspect business implementation for compliance and must not run project commands.

- [ ] **Step 4: Implement read-only Codex reviewer**

Invoke Codex with a task brief that limits reads to AGENTS、Rule Set、Base、Override、Catalog and referenced Agent/Skill definitions. Require structured JSON matching `review-report.schema.json`。Reject invalid output and never apply reviewer suggestions.

- [ ] **Step 5: Run tests and commit**

Run: `uv run pytest tests/test_checker.py tests/test_reviewer.py -q`

```powershell
git add -- src/project_execution_rules/checker.py src/project_execution_rules/status.py src/project_execution_rules/reviewer.py src/project_execution_rules/resources/schemas/review-report.schema.json tests/test_checker.py tests/test_reviewer.py
git commit -m "功能：检查并审查项目规则"
```

### Task 7：实现 Update、Repair、Rollback 和 Uninstall

**Files:**
- Create: `src/project_execution_rules/lifecycle.py`
- Create: `tests/test_lifecycle.py`

**Interfaces:**
- Produces: `plan_update()`、`plan_repair()`、`rollback_transaction()`、`plan_uninstall()`。
- All mutating functions consume `ChangePlan` and `Confirmation`, and return `OperationReport`。

- [ ] **Step 1: Write failing lifecycle tests**

Verify update dry-run reports changed/deprecated IDs and Override impact, repair fixes only managed structure, rollback rejects ambiguous targets, uninstall preserves Overrides and non-managed files.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest tests/test_lifecycle.py -q`

- [ ] **Step 3: Implement lifecycle operations on transaction engine**

Update user and project resources in separate transactions. Repair refuses semantic conflicts. Uninstall removes exact managed links and manifests but preserves `*.override.md` unless the user explicitly names an exact override target.

- [ ] **Step 4: Run tests and commit**

Run: `uv run pytest tests/test_lifecycle.py -q`

```powershell
git add -- src/project_execution_rules/lifecycle.py tests/test_lifecycle.py
git commit -m "功能：完成规则资源生命周期管理"
```

### Task 8：实现交互式 CLI、JSON 输出和退出码

**Files:**
- Create: `src/project_execution_rules/cli.py`
- Create: `src/project_execution_rules/presentation.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: Tasks 4–7 command services.
- Produces: Typer `app` with `install/init/status/check/review/doctor/update/repair/rollback/uninstall`。

- [ ] **Step 1: Write failing CliRunner tests**

Verify no-argument menu, interactive confirmations, `--dry-run`, `--yes`, `--format json`, non-interactive missing arguments, stable exit codes and error JSON.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest tests/test_cli.py -q`

- [ ] **Step 3: Implement interactive-first presentation**

No-argument invocation displays current root and menu. Mutations always show grouped user/project plans before confirmation. JSON mode writes only JSON to stdout; human diagnostics go to stderr. Cancellation exits without writes.

- [ ] **Step 4: Run tests and manual help smoke**

Run:

```powershell
uv run pytest tests/test_cli.py -q
uv run project-rules --help
uv run project-rules check --help
```

- [ ] **Step 5: Commit**

```powershell
git add -- src/project_execution_rules/cli.py src/project_execution_rules/presentation.py tests/test_cli.py
git commit -m "功能：提供交互式规则管理CLI"
```

### Task 9：端到端验收、文档和发行验证

**Files:**
- Create: `README.md`
- Create: `AGENTS.md`
- Create: `.gitignore`
- Create: `tests/integration/test_windows_workflow.py`
- Create: `tests/fixtures/python_project/pyproject.toml`
- Create: `tests/fixtures/python_project/src/example.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: a buildable wheel and documented local Windows workflow.

- [ ] **Step 1: Write isolated end-to-end test**

The test creates temporary HOME/LOCALAPPDATA and a temporary Git Python project, then executes install、init、check、status、update dry-run、repair dry-run and uninstall while asserting no project quality command was invoked.

- [ ] **Step 2: Run and confirm missing workflow support**

Run: `uv run pytest tests/integration/test_windows_workflow.py -q`

- [ ] **Step 3: Add user and contributor documentation**

README includes uv tool installation, interactive and JSON examples, Windows Developer Mode prerequisite, managed paths, non-goals, recovery and uninstall behavior. AGENTS routes Python/testing/documentation/Git tasks without duplicating the product Rules.

- [ ] **Step 4: Run the complete verification matrix**

Run:

```powershell
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyright
uv run pytest -q
uv build
uv run project-rules --help
git diff --check
```

Expected: all commands exit 0; all tests pass; wheel and sdist are built.

- [ ] **Step 5: Inspect built artifacts and secret boundaries**

Run:

```powershell
uv run python -c "from importlib.resources import files; print(files('project_execution_rules').joinpath('resources/catalog.yaml').is_file())"
git status --short
git ls-files | rg "(\\.env$|\\.pem$|\\.key$|pid|log$)"
```

Expected: bundled Catalog exists, only intentional files are tracked, secret/runtime scan has no matches.

- [ ] **Step 6: Commit**

```powershell
git add -- README.md AGENTS.md .gitignore pyproject.toml tests/integration tests/fixtures
git commit -m "文档：完成首版使用说明与验收"
```

### Task 10：独立复审与计划收尾

**Files:**
- Modify: `docs/superpowers/plans/2026-07-27-project-execution-rules-implementation.md`

**Interfaces:**
- Consumes: complete implementation and verification evidence.
- Produces: checked plan, reviewer findings closure and clean repository.

- [ ] **Step 1: Run an independent review**

Review against every section of the design, with emphasis on destructive operations, Windows path resolution, transaction restore, no business test execution, Rule trigger correctness and package resource completeness.

- [ ] **Step 2: Fix validated findings with targeted tests**

Each fix starts with a failing regression test, applies the minimum change, and reruns the targeted plus full suite.

- [ ] **Step 3: Mark completed plan checkboxes and verify no placeholders**

Run:

```powershell
rg -n "T[B]D|T[O]DO|F[I]XME|implement l[a]ter|Write tests for the a[b]ove" docs src tests
git diff --check
```

- [ ] **Step 4: Run final acceptance from a clean process**

Run:

```powershell
uv sync --locked
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyright
uv run pytest -q
uv build
uv run project-rules --help
git status --short --branch
```

- [ ] **Step 5: Commit plan closure**

```powershell
git add -- docs/superpowers/plans/2026-07-27-project-execution-rules-implementation.md
git commit -m "计划：记录首版开发验收结果"
```
