# Task 6 实施报告：Claude Project Scaffold and Project Ownership

## 状态

已在用户指定基线 `06617a0` 上完成 Task 6。未实现 Task 7 Checker/Doctor 重设计或 Task 9 CLI 选择。

## TDD 证据

1. 先新增 Claude scaffold/ownership 与 Adapter composition 测试，覆盖缺失 manifest、guide 初始化与保留、非空 Project Rule Extensions、无 Base copy/link、共享 Rule Set、碰撞、Claude-only 无 symlink 探测、staging 与 init 不隐式 install。
2. RED：`uv run pytest tests/test_claude_adapter.py tests/test_initialize.py -v` 得到目标能力失败；主要失败为 Claude project plan 为空、`ProjectSelection.adapters` 缺失、wrapper 仅支持 Codex、未校验 manifest。
3. GREEN：实现 Adapter-composed project plan、Claude scaffold、共享 Rule Set、闭包校验、碰撞检测和按计划 symlink probe 后，focused 集合通过。
4. 补充损坏 manifest 缺少 selected entry 的闭包测试，先确认 `DID NOT RAISE` RED，再校验 selection、entries 和 checksum closure，回归测试转 GREEN。
5. Review fix round 1 先补真实 CLI、extension ownership、exact closure、reserved/canonical target 回归；观察 6 个行为失败与缺失 composition API 的 collection RED，再逐项修复并转 GREEN。
6. Review fix round 2 用真实 leaf symlink 复现 compose 将 target 改写为 victim、guide symlink 错拒及 `.rules` symlink 绕过；4 个测试 RED 后改为 lexical identity + resolved parent/basename，并补 Windows junction/reparse 回归。
7. Review fix round 3 用真实 symlinked project root 复现 Adapter 生成真实路径但 composer 以 alias 做 lexical containment 而报 `ADAPTER_PROJECT_CONTRACT`；确认 RED 后在 planning 入口统一 resolved root，并让 detect、Adapters、composer、transaction、staging 与 check 使用同一真实根目录，回归转 GREEN。

## 实施内容

- `ProjectSelection` 记录 selected adapters；`plan_project_init` 按 Registry 顺序组合各 Adapter project plan。
- selected Adapter 必须存在 matching manifest v2；manifest selection 必须是按 Adapter 重新解析的完整 Catalog closure，entries 必须 exact、kind 正确，每个普通文件路径与 checksum 必须匹配；之后才验证 project closure 是 installed closure 子集。init 不安装或修复用户级资源。
- 真实 CLI `init` 只执行 project planning/apply；缺失或漂移的用户级资源明确提示单独运行 install，且 init 前后用户资源与 manifests 保持逐字节不变。
- Claude 仅在缺失时初始化 `.claude/CLAUDE.md`；既有普通 guide 与 leaf symlink guide 均保留，directory 或非 symlink reparse 冲突拒绝。
- Claude 仅在 extension target 缺失时生成非空 `.claude/rules/<rule-id>.project.md`；既有普通 extension 永不重写，unsafe target/ancestor 拒绝；不创建空 extension、skills/agents 空目录，也不复制或链接 Claude Base Rules/Skills/Agents。
- Claude guide 说明 Rule→Skill→Agent 职责，以及本地 `.claude/rules|skills|agents` 的项目生长入口。
- `.rules/ruleset.yaml` 由组合层唯一生成并作为 orchestrator reserved target；任何 Adapter 计划该 target 都立即报 contract error。
- project targets 以 lexical normalized project-relative path 识别 reserved target，再解析安全 parent 并拼回原 basename；不 dereference leaf symlink。最终 targets 约束在 project root 内，alias 对同一目标的不同 action/content 触发 `ADAPTER_PROJECT_COLLISION`。
- Claude 与 shared Rule Set 的 ancestor 链统一拒绝 symlink、Windows junction 和其他 reparse point；`.rules/ruleset.yaml` 的 reserved 检查先于 ancestor 解析。
- 用户可通过 symlinked project root 定位仓库；planning 入口只解析一次真实根目录，project facts、Adapters、composer、transaction、staging 与 CLI check 均共享该根目录，同时 project 内 descendant reparse 仍按既有规则拒绝。
- symlink capability 仅在实际 plan 含 symlink 时探测；Claude-only init 不依赖 Windows Developer Mode。
- staging 仅包含项目 guide、共享 Rule Set 与 Project Rule Extensions/Overrides，不包含 empty dirs 或 Base links。
- 项目生成内容保持项目所有权，不写入 Adapter managed manifest。

## 验证摘要

- Focused + CLI + Windows workflow：`91 passed`
- Full pytest：`172 passed`
- Ruff：`All checks passed!`
- Full Pyright：`0 errors, 0 warnings, 0 informations`
- Diff check：通过

## Concerns

- Task 6 只负责初始化与 project ownership；现有 Checker/Doctor 尚未按多 Adapter 重设计，留给 Task 7。
- CLI 多 Adapter 选择未接入，留给 Task 9；当前调用方可通过 `ProjectSelection.adapters` 使用组合能力。
