---
name: architecture
description: Apply module, interface, dependency, and data-flow architecture checks.
---

# Architecture Skill

## Steps
1. Map the current modules, public interfaces, dependencies, and key data flows.
2. Identify the composition root and verify external resources are explicitly assembled there.
3. Check each changed module has one responsibility and that dependency direction remains inward toward stable interfaces.
4. Validate public API compatibility, dependency direction, and critical data flows with focused tests or static checks.

## Tools
Use repository tree/search, symbol references, dependency metadata, and the project test/type-check commands.

## Checklist
- [ ] Module responsibilities are explicit.
- [ ] Composition root owns external resource assembly.
- [ ] Interfaces and dependency direction are validated.
- [ ] Critical data flows have evidence.

## Output
Report the inspected boundaries, dependency decisions, compatibility evidence, and unresolved architectural assumptions.
