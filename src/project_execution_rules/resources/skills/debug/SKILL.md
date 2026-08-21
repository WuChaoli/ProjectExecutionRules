---
name: debug
description: Apply evidence-first debugging and bounded remediation.
---

# Debug Skill

## Steps
1. Record the reproducible symptom, exact error text, environment, and recent changes.
2. Inspect relevant source, configuration, logs, and tests while excluding credentials and unrelated files.
3. State one root-cause hypothesis and run one targeted check at a time.
4. Add or run a regression test before applying the smallest fix.
5. Re-run the original reproduction and focused/full regression tests.

## Tools
Use repository search, file readers, and the project test runner; collect only authorized diagnostic output and redact sensitive data.

## Checklist
- [ ] Original reproduction is recorded.
- [ ] One hypothesis is tested at a time.
- [ ] A regression test covers the defect.
- [ ] Original and regression paths pass.

## Output
Report symptom, evidence, confirmed cause, minimal change, test commands/results, and remaining uncertainty.
