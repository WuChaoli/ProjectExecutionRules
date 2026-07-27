from __future__ import annotations

import json
from typing import Any

import typer
from rich.console import Console

from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.models import OutputFormat

console = Console()


def emit(payload: Any, output_format: OutputFormat) -> None:
    data = payload.to_dict() if hasattr(payload, "to_dict") else payload
    if output_format is OutputFormat.JSON:
        typer.echo(json.dumps(data, ensure_ascii=False))
    else:
        console.print(data)


def fail(error: ProjectRulesError, output_format: OutputFormat) -> None:
    if output_format is OutputFormat.JSON:
        typer.echo(json.dumps(error.to_dict(), ensure_ascii=False))
    else:
        console.print(f"[red]{error.message}[/red]", stderr=True)
        if error.remediation:
            console.print(error.remediation, stderr=True)
    raise typer.Exit(error.exit_code)


def confirm_or_cancel(message: str, *, yes: bool) -> bool:
    return yes or typer.confirm(message, default=False)
