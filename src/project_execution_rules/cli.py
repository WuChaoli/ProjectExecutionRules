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
    plan_uninstall,
    plan_update,
    plan_user_uninstall,
    rollback_transaction,
)
from project_execution_rules.models import OutputFormat
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
    ctx.invoke(command)


@app.command()
def install(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    yes: Annotated[bool, typer.Option("--yes")] = False,
    output_format: FormatOption = OutputFormat.HUMAN,
) -> None:
    """安装内置用户级 Rules、Agent 和 Skill。"""
    try:
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
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    yes: Annotated[bool, typer.Option("--yes")] = False,
    output_format: FormatOption = OutputFormat.HUMAN,
) -> None:
    """初始化 Python 项目的 Rules 结构。"""
    try:
        paths = _paths()
        facts = detect_project(root)
        catalog = load_builtin_catalog()
        core_domains = tuple(domain for domain, rule in catalog.rules.items() if rule.core)
        has_python_difference = bool(
            facts.python_requirement or facts.package_manager != "unknown" or facts.source_dirs
        )
        selection = ProjectSelection(
            core_domains=core_domains,
            override_domains=("python",) if has_python_difference else (),
        )
        plan = plan_project_init(root, facts, selection, paths)
        if dry_run:
            emit(plan, output_format)
            return
        confirmed = confirm_or_cancel("初始化当前项目 Rules？", yes=yes)
        operation = initialize_project(plan, root, paths, confirmed=confirmed)
        report = check_project(root, paths) if operation.changed else None
        emit(
            {
                "operation": operation.to_dict(),
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
        paths = _paths()
        catalog = load_builtin_catalog()
        user_plan = plan_update(paths, catalog)
        project_plan = (
            plan_project_update(root, catalog)
            if (root / ".rules" / "ruleset.yaml").is_file()
            else None
        )
        if dry_run:
            emit(
                {
                    "user": user_plan.to_dict(),
                    "project": project_plan.to_dict() if project_plan else None,
                },
                output_format,
            )
            return
        user_confirmed = confirm_or_cancel("更新用户级 Rules 资源？", yes=yes)
        emit(
            install_user_resources(user_plan, paths, confirmed=user_confirmed),
            output_format,
        )
        if project_plan is not None:
            project_confirmed = confirm_or_cancel(
                "更新项目 Rule Set 版本？",
                yes=yes,
            )
            emit(
                apply_lifecycle_plan(
                    project_plan,
                    root,
                    paths,
                    confirmed=project_confirmed,
                ),
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
        emit(
            install_user_resources(user_plan, paths, confirmed=user_confirmed),
            output_format,
        )
        project_confirmed = confirm_or_cancel("修复项目 Rules 结构？", yes=yes)
        emit(
            apply_lifecycle_plan(
                project_plan,
                root,
                paths,
                confirmed=project_confirmed,
            ),
            output_format,
        )
    except ProjectRulesError as error:
        fail(error, output_format)


@app.command()
def rollback(
    transaction_id: Annotated[str, typer.Argument(help="事务 ID。")],
    output_format: FormatOption = OutputFormat.HUMAN,
) -> None:
    """恢复未完成事务。"""
    try:
        rollback_transaction(_paths(), transaction_id)
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
        emit(
            apply_lifecycle_plan(
                project_plan,
                root,
                paths,
                confirmed=project_confirmed,
            ),
            output_format,
        )
        if user_plan is not None:
            user_confirmed = confirm_or_cancel("移除用户级 Rules 资源？", yes=yes)
            emit(
                apply_lifecycle_plan(
                    user_plan,
                    paths.home,
                    paths,
                    confirmed=user_confirmed,
                ),
                output_format,
            )
    except ProjectRulesError as error:
        fail(error, output_format)
