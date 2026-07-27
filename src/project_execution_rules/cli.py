from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Annotated

import typer

from project_execution_rules.catalog import load_builtin_catalog
from project_execution_rules.checker import check_project
from project_execution_rules.detection import detect_project
from project_execution_rules.doctor import CommandResult, run_doctor
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.initialize import (
    ProjectSelection,
    initialize_project,
    plan_project_init,
)
from project_execution_rules.install import (
    install_user_resources,
    plan_user_install,
    plan_user_repair,
)
from project_execution_rules.lifecycle import (
    apply_lifecycle_plan,
    plan_project_update,
    plan_repair,
    plan_rollback,
    plan_uninstall,
    plan_update,
    plan_user_uninstall,
    rollback_transaction,
    summarize_update,
)
from project_execution_rules.models import OutputFormat, RuleCatalog
from project_execution_rules.paths import UserPaths
from project_execution_rules.presentation import confirm_or_cancel, emit, fail
from project_execution_rules.reviewer import review_rules
from project_execution_rules.status import get_project_status

app = typer.Typer(
    name="project-rules",
    help="交互式管理 Codex 项目执行 Rules。",
    no_args_is_help=False,
)

RootOption = Annotated[
    Path,
    typer.Option("--root", help="目标 Git 项目目录。", resolve_path=True),
]
FormatOption = Annotated[
    OutputFormat,
    typer.Option("--format", help="输出格式。"),
]


def _paths() -> UserPaths:
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    return UserPaths.from_environment(os.environ, home)


def _runner(command: tuple[str, ...]) -> CommandResult:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(result.returncode, result.stdout, result.stderr)


def _select_core_domains(
    catalog: RuleCatalog,
    requested: str | None,
    *,
    interactive: bool,
) -> tuple[str, ...]:
    available = tuple(domain for domain, rule in catalog.rules.items() if rule.core)
    raw = requested
    if raw is None and interactive:
        typer.echo(f"可用 Core Rules：{', '.join(available)}")
        raw = typer.prompt("选择 Core Rules（逗号分隔）", default="all")
    if raw is None or raw.strip().lower() == "all":
        return available
    selected = tuple(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))
    unknown = tuple(domain for domain in selected if domain not in available)
    if unknown:
        raise ProjectRulesError(
            "RULE_SELECTION_INVALID",
            f"unknown Core Rule selection: {', '.join(unknown)}",
        )
    required = tuple(
        domain for domain in available if catalog.rules[domain].required and domain not in selected
    )
    if required:
        raise ProjectRulesError(
            "REQUIRED_RULE_MISSING",
            f"required Core Rules cannot be omitted: {', '.join(required)}",
        )
    return selected


def _selection_summary(
    catalog: RuleCatalog,
    domains: tuple[str, ...],
) -> dict[str, object]:
    return {
        "profile": "python",
        "rules": [
            {
                "domain": domain,
                "activation": catalog.rules[domain].activation.value,
                "paths": list(catalog.rules[domain].paths),
                "tasks": list(catalog.rules[domain].tasks),
                "commands": list(catalog.rules[domain].commands),
            }
            for domain in domains + catalog.profiles["python"]
        ],
    }


def _require_json_confirmation(
    output_format: OutputFormat,
    *,
    yes: bool,
    dry_run: bool,
) -> None:
    if output_format is OutputFormat.JSON and not yes and not dry_run:
        raise ProjectRulesError(
            "CONFIRMATION_REQUIRED",
            "JSON mutation commands require --yes",
            remediation="Add --yes or use --dry-run.",
        )


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """打开交互菜单或执行指定子命令。"""
    if ctx.invoked_subcommand is not None:
        return
    typer.echo("Project Execution Rules")
    choice = typer.prompt(
        "选择操作",
        default="status",
        show_default=True,
    ).strip()
    if choice.lower() in {"exit", "quit", "q"}:
        return
    commands = {
        "install": install,
        "init": init_project,
        "status": status,
        "check": check,
        "review": review,
        "doctor": doctor,
        "update": update,
        "repair": repair,
        "rollback": rollback,
        "uninstall": uninstall,
    }
    command = commands.get(choice)
    if command is None:
        raise typer.BadParameter(f"未知操作：{choice}")
    if choice in {
        "init",
        "status",
        "check",
        "review",
        "doctor",
        "update",
        "repair",
        "uninstall",
    }:
        root = Path(typer.prompt("选择项目目录", default="."))
        ctx.invoke(command, root=root)
    elif choice == "rollback":
        transaction_id = typer.prompt("事务 ID")
        ctx.invoke(command, transaction_id=transaction_id)
    else:
        ctx.invoke(command)


@app.command()
def install(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    yes: Annotated[bool, typer.Option("--yes")] = False,
    output_format: FormatOption = OutputFormat.HUMAN,
) -> None:
    """安装内置用户级 Rules、Agent 和 Skill。"""
    try:
        _require_json_confirmation(
            output_format,
            yes=yes,
            dry_run=dry_run,
        )
        paths = _paths()
        plan = plan_user_install(paths, load_builtin_catalog())
        if dry_run:
            emit(plan, output_format)
            return
        confirmed = confirm_or_cancel("安装用户级 Rules 资源？", yes=yes)
        emit(
            install_user_resources(plan, paths, confirmed=confirmed),
            output_format,
        )
    except ProjectRulesError as error:
        fail(error, output_format)


@app.command("init")
def init_project(
    root: RootOption = Path("."),
    core: Annotated[
        str | None,
        typer.Option("--core", help="逗号分隔的 Core Rule 域，默认 all。"),
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    yes: Annotated[bool, typer.Option("--yes")] = False,
    output_format: FormatOption = OutputFormat.HUMAN,
) -> None:
    """初始化 Python 项目的 Rules 结构。"""
    try:
        _require_json_confirmation(
            output_format,
            yes=yes,
            dry_run=dry_run,
        )
        paths = _paths()
        facts = detect_project(root)
        catalog = load_builtin_catalog()
        core_domains = _select_core_domains(
            catalog,
            core,
            interactive=not yes and not dry_run,
        )
        has_python_difference = bool(
            facts.python_requirement or facts.package_manager != "unknown" or facts.source_dirs
        )
        selection = ProjectSelection(
            core_domains=core_domains,
            override_domains=("python",) if has_python_difference else (),
        )
        user_plan = plan_user_install(paths, catalog)
        project_plan = plan_project_init(
            root,
            facts,
            selection,
            paths,
            verify_user_install=False,
        )
        summary = _selection_summary(catalog, core_domains)
        user_operation = None
        if dry_run:
            emit(
                {
                    "selection": summary,
                    "user": user_plan.to_dict(),
                    "project": project_plan.to_dict(),
                },
                output_format,
            )
            return
        if user_plan.changes:
            if not yes:
                emit(
                    {"selection": summary, "user": user_plan.to_dict()},
                    output_format,
                )
            user_confirmed = confirm_or_cancel(
                "先安装或更新用户级 Rules 资源？",
                yes=yes,
            )
            user_operation = install_user_resources(
                user_plan,
                paths,
                confirmed=user_confirmed,
            )
            if output_format is OutputFormat.HUMAN:
                emit(user_operation, output_format)
            if not user_operation.changed:
                raise ProjectRulesError(
                    "USER_INSTALL_REQUIRED",
                    "project initialization requires the user-level installation",
                )
        project_plan = plan_project_init(root, facts, selection, paths)
        if not yes:
            emit(
                {"selection": summary, "project": project_plan.to_dict()},
                output_format,
            )
        confirmed = confirm_or_cancel("初始化当前项目 Rules？", yes=yes)
        operation = initialize_project(
            project_plan,
            root,
            paths,
            confirmed=confirmed,
        )
        report = check_project(root, paths) if operation.changed else None
        emit(
            {
                "operation": operation.to_dict(),
                "user_operation": (
                    user_operation.to_dict() if user_operation is not None else None
                ),
                "check": report.to_dict() if report else None,
            },
            output_format,
        )
        if report is not None and report.issues:
            raise typer.Exit(2)
    except ProjectRulesError as error:
        fail(error, output_format)


@app.command()
def status(
    root: RootOption = Path("."),
    output_format: FormatOption = OutputFormat.HUMAN,
) -> None:
    """显示当前项目 Rules 状态。"""
    try:
        emit(get_project_status(root, _paths()), output_format)
    except ProjectRulesError as error:
        fail(error, output_format)


@app.command()
def check(
    root: RootOption = Path("."),
    output_format: FormatOption = OutputFormat.HUMAN,
) -> None:
    """执行确定性 Rules 结构检查。"""
    try:
        report = check_project(root, _paths())
        emit(report, output_format)
        if report.issues:
            raise typer.Exit(2)
    except ProjectRulesError as error:
        fail(error, output_format)


@app.command()
def review(
    root: RootOption = Path("."),
    output_format: FormatOption = OutputFormat.HUMAN,
) -> None:
    """启动只读 Codex Rules Reviewer。"""
    try:
        emit(review_rules(root, _paths()), output_format)
    except ProjectRulesError as error:
        fail(error, output_format)


@app.command()
def doctor(
    root: RootOption = Path("."),
    output_format: FormatOption = OutputFormat.HUMAN,
) -> None:
    """诊断 Git、Codex、链接和 Rules 基础设施。"""
    try:
        report = run_doctor(root, _paths(), _runner)
        emit(report, output_format)
        if any(issue.severity == "error" for issue in report.issues):
            raise typer.Exit(2)
    except ProjectRulesError as error:
        fail(error, output_format)


@app.command()
def update(
    root: RootOption = Path("."),
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    yes: Annotated[bool, typer.Option("--yes")] = False,
    output_format: FormatOption = OutputFormat.HUMAN,
) -> None:
    """更新内置用户级资源。"""
    try:
        _require_json_confirmation(
            output_format,
            yes=yes,
            dry_run=dry_run,
        )
        paths = _paths()
        catalog = load_builtin_catalog()
        user_plan = plan_update(paths, catalog)
        project_plan = (
            plan_project_update(root, catalog)
            if (root / ".rules" / "ruleset.yaml").is_file()
            else None
        )
        impact = summarize_update(root, paths, catalog)
        if dry_run:
            emit(
                {
                    "user": user_plan.to_dict(),
                    "project": project_plan.to_dict() if project_plan else None,
                    "impact": impact,
                },
                output_format,
            )
            return
        if not yes:
            emit({"impact": impact}, output_format)
        user_confirmed = confirm_or_cancel("更新用户级 Rules 资源？", yes=yes)
        user_report = install_user_resources(
            user_plan,
            paths,
            confirmed=user_confirmed,
        )
        if output_format is OutputFormat.HUMAN:
            emit(user_report, output_format)
        if user_plan.changes and not user_report.changed:
            raise ProjectRulesError(
                "USER_UPDATE_REQUIRED",
                "project update requires the user-level Rules update to complete first",
            )
        project_report = None
        if project_plan is not None:
            project_confirmed = confirm_or_cancel(
                "更新项目 Rule Set 版本？",
                yes=yes,
            )
            project_report = apply_lifecycle_plan(
                project_plan,
                root,
                paths,
                confirmed=project_confirmed,
            )
            if output_format is OutputFormat.HUMAN:
                emit(project_report, output_format)
        if output_format is OutputFormat.JSON:
            emit(
                {
                    "user": user_report.to_dict(),
                    "project": project_report.to_dict() if project_report else None,
                },
                output_format,
            )
    except ProjectRulesError as error:
        fail(error, output_format)


@app.command()
def repair(
    root: RootOption = Path("."),
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    yes: Annotated[bool, typer.Option("--yes")] = False,
    output_format: FormatOption = OutputFormat.HUMAN,
) -> None:
    """修复 Rules 托管结构，不修改业务代码。"""
    try:
        _require_json_confirmation(
            output_format,
            yes=yes,
            dry_run=dry_run,
        )
        paths = _paths()
        user_plan = plan_user_repair(paths, load_builtin_catalog())
        project_plan = plan_repair(root, paths)
        if dry_run:
            emit(
                {
                    "user": user_plan.to_dict(),
                    "project": project_plan.to_dict(),
                },
                output_format,
            )
            return
        user_confirmed = confirm_or_cancel("修复用户级 Rules 资源？", yes=yes)
        user_report = install_user_resources(
            user_plan,
            paths,
            confirmed=user_confirmed,
        )
        if output_format is OutputFormat.HUMAN:
            emit(user_report, output_format)
        if user_plan.changes and not user_report.changed:
            raise ProjectRulesError(
                "USER_REPAIR_REQUIRED",
                "project repair requires the user-level Rules repair to complete first",
            )
        project_plan = plan_repair(root, paths)
        project_confirmed = confirm_or_cancel("修复项目 Rules 结构？", yes=yes)
        project_report = apply_lifecycle_plan(
            project_plan,
            root,
            paths,
            confirmed=project_confirmed,
        )
        if output_format is OutputFormat.HUMAN:
            emit(project_report, output_format)
        else:
            emit(
                {
                    "user": user_report.to_dict(),
                    "project": project_report.to_dict(),
                },
                output_format,
            )
    except ProjectRulesError as error:
        fail(error, output_format)


@app.command()
def rollback(
    transaction_id: Annotated[str, typer.Argument(help="事务 ID。")],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    yes: Annotated[bool, typer.Option("--yes")] = False,
    output_format: FormatOption = OutputFormat.HUMAN,
) -> None:
    """恢复未完成事务。"""
    try:
        _require_json_confirmation(
            output_format,
            yes=yes,
            dry_run=dry_run,
        )
        paths = _paths()
        plan = plan_rollback(paths, transaction_id)
        if dry_run:
            emit(plan, output_format)
            return
        confirmed = confirm_or_cancel("恢复此事务？", yes=yes)
        if not confirmed:
            emit({"rolled_back": None}, output_format)
            return
        rollback_transaction(paths, transaction_id)
        emit({"rolled_back": transaction_id}, output_format)
    except ProjectRulesError as error:
        fail(error, output_format)


@app.command()
def uninstall(
    root: RootOption = Path("."),
    include_user: Annotated[bool, typer.Option("--include-user")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    yes: Annotated[bool, typer.Option("--yes")] = False,
    output_format: FormatOption = OutputFormat.HUMAN,
) -> None:
    """移除托管 Rules 资源并保留 Override。"""
    try:
        _require_json_confirmation(
            output_format,
            yes=yes,
            dry_run=dry_run,
        )
        paths = _paths()
        project_plan = plan_uninstall(root, paths, include_user=False)
        user_plan = plan_user_uninstall(paths) if include_user else None
        if dry_run:
            emit(
                {
                    "project": project_plan.to_dict(),
                    "user": user_plan.to_dict() if user_plan else None,
                },
                output_format,
            )
            return
        project_confirmed = confirm_or_cancel("移除项目 Rules 资源？", yes=yes)
        project_report = apply_lifecycle_plan(
            project_plan,
            root,
            paths,
            confirmed=project_confirmed,
        )
        if output_format is OutputFormat.HUMAN:
            emit(project_report, output_format)
        user_report = None
        if user_plan is not None:
            user_confirmed = confirm_or_cancel("移除用户级 Rules 资源？", yes=yes)
            user_report = apply_lifecycle_plan(
                user_plan,
                paths.home,
                paths,
                confirmed=user_confirmed,
            )
            if output_format is OutputFormat.HUMAN:
                emit(user_report, output_format)
        if output_format is OutputFormat.JSON:
            emit(
                {
                    "project": project_report.to_dict(),
                    "user": user_report.to_dict() if user_report else None,
                },
                output_format,
            )
    except ProjectRulesError as error:
        fail(error, output_format)
