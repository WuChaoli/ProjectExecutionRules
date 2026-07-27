from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def run_command(
    command: tuple[str, ...],
    *,
    input_text: str | None = None,
) -> CommandResult:
    executable = shutil.which(command[0])
    if executable is None:
        return CommandResult(127, "", f"command not found: {command[0]}")
    try:
        result = subprocess.run(
            (executable, *command[1:]),
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        return CommandResult(127, "", f"failed to execute {command[0]}: {error}")
    return CommandResult(result.returncode, result.stdout, result.stderr)
