from __future__ import annotations

import json
import subprocess
import uuid
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from importlib.resources import as_file
from pathlib import Path

import jsonschema

from project_execution_rules.catalog import resource_root
from project_execution_rules.doctor import CommandResult
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.paths import UserPaths

ReviewRunner = Callable[[tuple[str, ...], str, Path], CommandResult]


@dataclass(frozen=True, slots=True)
class ReviewReport:
    status: str
    issues: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {"status": self.status, "issues": list(self.issues)}


def _default_runner(
    command: tuple[str, ...],
    prompt: str,
    output_path: Path,
) -> CommandResult:
    result = subprocess.run(
        command,
        input=prompt,
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(result.returncode, result.stdout, result.stderr)


def review_rules(
    root: Path,
    paths: UserPaths,
    *,
    runner: ReviewRunner = _default_runner,
) -> ReviewReport:
    schema_resource = resource_root().joinpath("schemas/review-report.schema.json")
    output_path = paths.state_home / "review-cache" / f"{uuid.uuid4().hex}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = """只读审查当前项目的 Rules 治理层。
只允许读取 AGENTS.md、.rules/、用户级 Rules Catalog 和被引用的 Rules Agent/Skill。
检查完整性、清晰度、重复、矛盾、Trigger、预算、路由和 Override 语义。
不得审计业务代码，不得运行项目测试、构建或外部服务，不得修改任何文件。
最终只输出符合指定 JSON Schema 的对象。
"""
    with ExitStack() as stack:
        schema_path = stack.enter_context(as_file(schema_resource))
        command = (
            "codex",
            "exec",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--cd",
            str(root.resolve()),
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "-",
        )
        result = runner(command, prompt, output_path)
        if result.returncode != 0:
            raise ProjectRulesError(
                "REVIEW_FAILED",
                "Codex Rules review failed",
                evidence={"stderr": result.stderr},
            )
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            jsonschema.validate(payload, schema)
        except (OSError, ValueError, jsonschema.ValidationError) as error:
            raise ProjectRulesError(
                "REVIEW_REPORT_INVALID",
                f"invalid review report: {error}",
            ) from error
    return ReviewReport(
        status=str(payload["status"]),
        issues=tuple(payload["issues"]),
    )
