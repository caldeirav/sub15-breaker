# Documentation index

The supported research domain is **AgentDojo simulated banking**. The local harness, shared contracts and controlled Actor service have distinct trust/usage scopes; none is automatically a financial-policy guard or latency result. Use [GitHub roadmap #14](https://github.com/caldeirav/sub15-breaker/issues/14) and owning issues for current delivery status. Do not use the retired shell dataset or command-only sidecar as the banking architecture.

## Current authority and how to use it

| Document | Purpose |
| --- | --- |
| [Project scope](project-scope.md) | Domain, trust boundaries, implemented versus planned features |
| [Specification](../specs/001-breaker.md) | Normative banking target and acceptance requirements |
| [Golden environment](golden-data.md) | Pinned upstream tasks/tools/checkers; metric meanings and limitations |
| [Evaluation design](evaluation-design-review.md) | Harness correctness versus agent quality, controls and unbiased reporting |
| [Banking runbook](banking-feasibility.md) | Actual commands, prerequisites and accepted evidence |
| [Trace contract](mlflow-trace-contract.md) | Model/tool/judge coverage and per-trace score ownership |
| [Actor service guide](banking-actor-service.md) | Controlled Actor execution, external transactional state, identity, evidence outbox and local operation |
| [Harness acceptance v3](banking-harness-acceptance-v3.md) | Active acceptance policy: correct evaluation, not universal agent success |
| [Human checklist](validation/block-02-harness-review.md) / [acceptance record](validation/block-02.json) | @caldeirav's scoped acceptance and reproducible inspection steps |
| [Implementation plan](implementation-plan.md) / [next iteration](next-iteration.md) | Remaining blocks and accepted record-only 03a scope |
| [Block 03a contracts](banking-contracts-03a.md) | Owner-confirmed choices, shared types, schema semantics and record-only fixture evidence |
| [Infrastructure](infra.md) | Separate accepted control plane and non-executing fixtures |
| [Agent/harness boundaries](agent-harness-architecture.md) | Suite-neutral runtime and harness contracts; AgentDojo task/tool/checker adapter boundary |
| [Guard benchmark](benchmark-guard-experiment.md) | One flow, common Substrate guard boundary, compact neural classifier versus LLM, labels and fair timing |
| [Legacy compatibility](legacy-compatibility.md) | Old modules/examples that are not the supported banking path |
| [Documentation alignment audit](documentation-audit.md) | What was reviewed/corrected, immutable evidence and validation boundaries |

Block 03a's requirements were clarified before coding. Its record-only implementation has independent technical approval and fresh human acceptance by @caldeirav on 2026-10-31, but is not a delivered security boundary. No live-pilot integration or financial authorization is included. Additional business/security scope still needs clarification; hidden golden answers remain evaluator-only.

## Frozen experiment protocols and historical evidence

These files are versioned evidence copied/hashed into recorded MLflow runs. They are retained byte-for-byte, not silently updated to make earlier runs look passed:

- [Metric v2 protocol](banking-metric-contract-v2.md): active four-criterion definitions; its original 3/3 agent-win **acceptance clause** is superseded by harness v3.
- [Evidence v2.1 amendment](banking-evidence-v2.1.md): private row equality, service features and failure accounting.
- [Provenance v2.2 amendment](banking-provenance-v2.2.md): exact native envelope schemas with all three verdicts.
- [Registry correction](banking-registry-validation-note.md): local SQLite registration race and its bounded fix.
- [Harness v3 policy](banking-harness-acceptance-v3.md): supersedes only win-rate/PR-blocking clauses, not golden outcomes or historical statuses. Its “pending until owner reports” wording describes the recording-time condition; acceptance is now in `validation/block-02.json`.

The following are **historical review/checklist snapshots**, not today's to-do list or a requirement to reopen #20, repair #25, or reaccept an already accepted block:

- [Block-01 checklist](validation/block-01-infra.md) and [record](validation/block-01.json): accepted foundation, merged PR #18.
- [Initial block-02 checklist](validation/block-02-banking.md), [initial independent review](validation/block-02-independent-review.md), [v2 review](validation/block-02-v2-review.md), [v2 independent review](validation/block-02-v2-independent-review.md).
- [Current-scope independent review](validation/block-02-harness-independent-review.md): accepted harness-v3 technical review, separate from human acceptance.

Current block-02 delivery is [merged PR #26](https://github.com/caldeirav/sub15-breaker/pull/26), commit `1e32c54eec0cfe060013487789924baa57470894`. Source run `e56a427a9592460f81f246bc3c0d6e29` stays FAILED under its old policy; derived harness assessment `53b476bed53446ebac25753aaa9a8b80` passes under v3. Both are truthful records of different acceptance scopes. Local MLflow URLs require access to the owner's tracking server.

Historical Bash/alternative-benchmark research is available in [the previous documentation revision](https://github.com/caldeirav/sub15-breaker/tree/1e32c54eec0cfe060013487789924baa57470894). It is not a current dataset recommendation. Current docs intentionally do not instruct users to assemble that corpus or run its destructive examples.
