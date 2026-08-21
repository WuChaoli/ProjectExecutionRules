# Task 3B implementation report

Implemented strict managed manifest v2 consumers and Adapter transaction metadata without retaining `managed-user.json` compatibility.

## Implementation

- Codex install, checker, doctor, lifecycle, and reviewer consumers use `managed-user-codex.json` through `UserPaths.manifest_path(AdapterId.CODEX)` and validate the expected Adapter.
- Install persists deterministic `ManagedManifest` v2 content, including `ManagedSelection` and Home-relative `rule|skill|agent` entries.
- `FileTransaction` persists optional Adapter metadata while non-Adapter transactions retain the legacy no-Adapter shape.
- Persistent rollback and rollback preview accept an expected Adapter and validate missing, invalid, or mismatched metadata before processing or presenting any originals. The current Codex-only CLI explicitly passes `AdapterId.CODEX` to both paths. Non-Adapter rollback still accepts manifests without Adapter metadata.
- Install and uninstall share Adapter path safety checks: lexical containment, canonical containment, direct symlink rejection, and ancestor symlink/junction/reparse rejection. Install cannot claim matching content through an unsafe path; uninstall never deletes such a target.

## TDD evidence

Initial Task 3B tests failed because the v2 Codex manifest did not exist and `FileTransaction` did not accept Adapter metadata. Fix-round tests then failed because persistent rollback lacked `expected_adapter`, user lifecycle transactions omitted Adapter metadata, install/uninstall bypassed reparse ownership checks, and the Codex-only CLI omitted expected Adapter validation from both preview and execution. The implementation was added only after these RED runs.

## Verification

- Focused CLI/lifecycle suite: 29 passed.
- Full pytest: 113 passed with one pre-existing Windows command-wrapper UTF-8 thread warning.
- Ruff: all checks passed.
- Full Pyright: 0 errors, 0 warnings, 0 informations.
- `git diff --check`: passed.

## Scope

Did not implement CodexAdapter or Rule Set v2 (Task 4), Claude resources (Task 5), or multi-Adapter lifecycle/CLI redesign (Task 8).
