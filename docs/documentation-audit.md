# Banking documentation alignment audit

Scope: documentation-only commit [`b5b630c`](https://github.com/caldeirav/sub15-breaker/commit/b5b630c), pushed before block-03a implementation. That maintenance changed no harness, golden definitions, dependencies or attestations. Subsequent [block-03a feature work](banking-contracts-03a.md) is a separate scope; checks below describe the documentation commit, not a claim that later code is absent.

## Findings corrected

| Finding | Correction |
| --- | --- |
| README still devoted most of its content/setup/map to a command corpus and shell classifier, even inside a legacy disclosure | Replaced with banking-first overview, actual current/target paths, AgentDojo golden tasks, correct prerequisites, supported commands and pending 03a status |
| Evaluation review still recommended shell/alternative benchmark construction | Replaced with the selected banking evaluation design; prior research is available through a pinned Git-history link |
| Banking guide mixed initial two-judge/dictionary output with the current four-criterion native envelope schema and stale review blockers | Rewritten from implemented code: 17 cases/68 reviews, native raw string plus decoded fields, accepted harness scope, non-gating quality and recorded source/derived roles |
| Scope/spec prose could imply gateway/Actor contracts already exist | Explicit target-only labeling and owner clarification required before 03a code |
| Infrastructure and onboarding implied a shell executor/legacy sidecar was a banking prerequisite | Correct banking versus foundation split; placeholder inventory and legacy compatibility guide |
| Historical “pending/not accepted” records could override current acceptance | Added clear chronology/index/navigation without rewriting their raw findings or JSON attestations |
| Next-step text still mentioned merging the already merged harness | Recorded PR #26/commit and made unresolved money/authority/integration choices explicit |

## Documentation coverage

- Root `README.md`; all current `docs/*.md`; `specs/001-breaker.md`.
- Infrastructure runbook and block-01 checklist; all block-02 review/checklist documents, acceptance records and evidence protocol files.
- New docs/validation indexes, banking golden environment and legacy compatibility guides.
- `.github/pull_request_template.md`, `.env.example` explanatory comments, `Dockerfile.sidecar` compatibility comments and `k8s/README.md` inventory. Executable statements and manifests are not changed.
- `LICENSE`, dependency files and JSON acceptance attestations reviewed and retained. Legacy code/data remain for compatibility; no dataset is deleted or silently substituted.

## Preservation and validation

The five versioned metric/evidence/provenance/registry/harness-policy Markdown files copied or hashed into recorded runs are retained byte-for-byte and classified in [the documentation index](README.md#frozen-experiment-protocols-and-historical-evidence). Earlier win-rate clauses are historical; current acceptance comes from harness v3 and the named block record. Historical run statuses, raw Feedback, tester/date evidence and task failures remain unchanged.

Completed checks: **145 offline tests passed** via `bash scripts/test.sh`; **28 Markdown documents** passed local-link, heading-anchor and fence checks; primary README/evaluation/golden guides passed a scan excluding the retired corpus recommendations. The five frozen protocol files and two JSON acceptance attestations match HEAD byte-for-byte. Dockerfile/environment changes are comments only; executable instructions/config values, Python modules, dependencies and manifests remain unchanged.

No model/provider calls, cluster changes, dependency updates or block-03a contract code were performed. Documentation changes do not constitute new human acceptance of any future block.

## Implementation hold point

Commit/push the documentation correction first. Then clarify block 03a's scope, trusted policy/context source, exact monetary representation and intended initial policy depth with the owner. Do not write contract implementation, wire it into the pilot, or decide those business/security semantics merely from the old prototype.
