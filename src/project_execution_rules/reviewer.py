from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from importlib.resources import as_file
from pathlib import Path

import jsonschema

from project_execution_rules.catalog import resource_root
from project_execution_rules.commands import CommandResult, run_command
from project_execution_rules.errors import ProjectRulesError
from project_execution_rules.managed import sha256_bytes
from project_execution_rules.models import AdapterId
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
    return run_command(command, input_text=prompt)


def review_rules(
    root: Path,
    paths: UserPaths,
    *,
    runner: ReviewRunner = _default_runner,
) -> ReviewReport:
    schema_resource = resource_root().joinpath("schemas/review-report.schema.json")
    output_path = paths.state_home / "review-cache" / f"{uuid.uuid4().hex}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = """只读审查隔离目录中的 Rules 治理层。
只允许读取 project/AGENTS.md、project/.rules/、user/rules/ 和 codex/ 中的治理资源。
review-context.json 与 user/managed-user-codex.json 是 CLI 从原项目链接和 Codex 托管 manifest
生成的确定性证据；必须复算复制文件的 SHA-256 后再判断来源链和完整性。
检查完整性、清晰度、重复、矛盾、Trigger、预算、路由和 Override 语义。
不得审计业务代码，不得运行项目测试、构建或外部服务，不得修改任何文件。
最终只输出符合指定 JSON Schema 的对象。
"""
    with ExitStack() as stack:
        schema_path = stack.enter_context(as_file(schema_resource))
        paths.state_home.mkdir(parents=True, exist_ok=True)
        review_root = Path(stack.enter_context(tempfile.TemporaryDirectory(dir=paths.state_home)))
        project_copy = review_root / "project"
        rules_copy = project_copy / ".rules"
        rules_copy.mkdir(parents=True)
        base_links: list[dict[str, object]] = []
        agents = root.resolve() / "AGENTS.md"
        if agents.is_file() and not agents.is_symlink():
            shutil.copy2(agents, project_copy / "AGENTS.md")
        source_rules = root.resolve() / ".rules"
        if source_rules.is_dir():
            for source in source_rules.iterdir():
                if source.is_symlink():
                    resolved_source = source.resolve()
                    try:
                        resolved_source.relative_to(paths.rules_home.resolve())
                    except ValueError as error:
                        raise ProjectRulesError(
                            "REVIEW_INPUT_UNSAFE",
                            f"Rule link escapes the managed Rule home: {source}",
                        ) from error
                    shutil.copy2(resolved_source, rules_copy / source.name)
                    relative_target = resolved_source.relative_to(paths.rules_home.resolve())
                    base_links.append(
                        {
                            "project_path": f"project/.rules/{source.name}",
                            "target": f"user/rules/{relative_target.as_posix()}",
                            "sha256": sha256_bytes(resolved_source.read_bytes()),
                            "link_verified": True,
                        }
                    )
                elif source.is_file():
                    shutil.copy2(source, rules_copy / source.name)
        for source, target in (
            (paths.rules_home, review_root / "user" / "rules"),
            (
                paths.codex_agents / "rules-reviewer.toml",
                review_root / "codex" / "agents" / "rules-reviewer.toml",
            ),
            (
                paths.codex_skills / "rules-reviewer" / "SKILL.md",
                review_root / "codex" / "skills" / "rules-reviewer" / "SKILL.md",
            ),
            (
                paths.codex_skills / "agent-governance" / "SKILL.md",
                review_root / "codex" / "skills" / "agent-governance" / "SKILL.md",
            ),
            (
                paths.codex_skills / "tool-governance" / "SKILL.md",
                review_root / "codex" / "skills" / "tool-governance" / "SKILL.md",
            ),
        ):
            if source.is_dir():
                shutil.copytree(source, target, symlinks=False)
            elif source.is_file() and not source.is_symlink():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        manifest_source = paths.manifest_path(AdapterId.CODEX)
        if manifest_source.is_file() and not manifest_source.is_symlink():
            manifest_target = review_root / "user" / "managed-user-codex.json"
            manifest_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(manifest_source, manifest_target)
        catalog_source = paths.rules_home / "catalog.yaml"
        context = {
            "schema_version": 1,
            "catalog": {
                "logical_path": "user/rules/catalog.yaml",
                "sha256": (
                    sha256_bytes(catalog_source.read_bytes())
                    if catalog_source.is_file() and not catalog_source.is_symlink()
                    else None
                ),
            },
            "managed_manifest": {
                "logical_path": "user/managed-user-codex.json",
                "present": manifest_source.is_file() and not manifest_source.is_symlink(),
            },
            "base_links": base_links,
        }
        (review_root / "review-context.json").write_text(
            json.dumps(context, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        command = (
            "codex",
            "exec",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--cd",
            str(review_root),
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
