---
name: external-services
description: Apply bounded external-service integration practices.
---

# External Services Skill

## Steps
1. Confirm endpoint, protocol, capabilities, and failure semantics from the real client, configuration, and official contract.
2. Use a Fake or controlled Mock for local development and tests by default.
3. Define bounded timeout, retry, and failure behavior before integration.
4. Obtain explicit authorization for real calls and document credentials, data exposure, and side-effect boundaries.
5. Run isolated integration verification and record what could not be exercised.

## Tools
Use configured clients, contract documentation, controlled test doubles, and the project integration test runner; never infer a contract from a guessed endpoint.

## Checklist
- [ ] Contract and capability evidence is current.
- [ ] Default path uses a controlled test double.
- [ ] Timeout, retry, and failure behavior is bounded.
- [ ] Real integration authorization and side effects are explicit.

## Output
Report contract evidence, test-double behavior, integration authorization, side-effect boundaries, and failed/unverified cases.
