---
name: observability
description: Apply evidence-based observability and safe diagnostic collection.
---

# Observability Skill

## Steps
1. Identify the failure or operation and the signal needed to locate it.
2. Read current logging, tracing, metrics, and runtime configuration sources.
3. Collect the minimum authorized context, excluding credentials and sensitive payloads.
4. Verify that the signal is emitted, correlated to the operation, and readable by its intended consumer.
5. Base performance conclusions on measurements rather than code shape.

## Tools
Use configured logs, trace viewers, metrics queries, and runtime status commands only within the authorized scope; redact outputs before reporting.

## Checklist
- [ ] Signal and correlation key are defined.
- [ ] Collection is minimal and sanitized.
- [ ] Signal production, correlation, and reading are verified.
- [ ] Performance claims have measurements.

## Output
Report signal sources, collected evidence, sanitization, verification results, and measurement limits.
