# Actor readiness diagnostic verification — #62

**Eight fixed readiness observations passed. The cause of the old failure remains
unconfirmed; no complete model-backed rehearsal is claimed.**

PRs #57 and #61 were reviewed and merged to main (`0619128`, `a3b75db`), with
green Python3.11–3.13 CI and609 tests rechecked locally. This investigation is
the scoped follow-up in PR #63; [protocol and boundaries](actor-readiness-plan.md).

## What changed

Previously, `invalid_runtime_json` discarded the response status/type and did not
distinguish driver→Actor from Actor→store. Runtime HTTP failures now retain only
safe metadata: boundary/operation ID, status, known media type, bounded byte count
and digest, elapsed time and exception category. Response bodies, URLs, tokens,
banking payloads and raw exception messages are not logged. Strict JSON parsing,
verified identity, fail-closed decisions and zero automatic retries remain.

Streaming enforces the body limit before buffering an unbounded response. Safe
nested hops survive the Actor's structured error envelope and partial-case record;
errors are logged before Actor deletion/egress restoration. Successful readiness
returns safe inner-hop metadata, without bypassing any authentication or checks.

Tests cover non-JSON, empty/truncated/oversized replies, auth errors, connection/
read timeout, sanitization, propagation and immutable probe markers. Source
`4589899` passed622 tests on Python3.11–3.13 and green CI before probes. A later
host-CLI regression makes failed/incomplete probe batches exit nonzero; it changes
no observed result, image or runtime behavior from the executed batch.
Final local regression count: **623 passed on Python3.11–3.13**.

## Frozen non-effectful batch

- Four fresh gVisor Actors, each with one first and one explicitly declared
  subsequent authenticated readiness call. All eight were fixed before execution,
  not repeated until green or used as hidden model warmups.
- Same2s native control hook and5s Actor/store readiness budget; diagnostic driver
  timeout15s. Driver identity, returned Actor UID and ticket lifetime900 verified.
- No `/create`, prepare, claim, execute, banking tool, classifier, LLM or judge.
  Four Actor allocations are infrastructure operations, not acting-model requests.
- Diagnostic image:
  `localhost:5002/breaker-banking@sha256:19f625ed48a7c5be2e54429284a390108ba659df5bb93965b9858a974860174d`.
- Same PVC/key, every stored historical row, active reservation and256-trial limit
  verified unchanged across image deployment. No history deletion/reset or shared
  model reload.

| Actor | Observation | Driver→Actor HTTP | Actor→store HTTP | End-to-end ms | Identity/profile |
| --- | --- | ---: | ---: | ---: | --- |
| P01 | First |200 |200 |118.663 |Verified |
| P01 | Subsequent |200 |200 |59.044 |Verified |
| P02 | First |200 |200 |103.593 |Verified |
| P02 | Subsequent |200 |200 |51.850 |Verified |
| P03 | First |200 |200 |108.722 |Verified |
| P03 | Subsequent |200 |200 |59.477 |Verified |
| P04 | First |200 |200 |98.715 |Verified |
| P04 | Subsequent |200 |200 |53.474 |Verified |

Both hops returned JSON; per-hop timings, byte counts and digests are retained.
These are control-plane readiness timings, **not classifier or native claim
benchmarks**, availability guarantees or proof of cold model weights.

All Actors deleted; hook restored; full ledger, stored history and capacity
reservation unchanged before/after. **Zero new trials/model/tool/judge requests**.
Pre-restoration logs are retained, even though this batch had no failure.

## Interpretation and remaining gate

The old nd8 failure **did not reproduce**. We have closed the observability gap
and verified the current readiness path in a bounded batch, but cannot identify
the old upstream status/body/connection cause. Do not claim a JWT, timeout or
connection fix merely from these successes; do not claim #52 was diagnosed.

#62 therefore stays open, as do owner gates #45/#48. The old failed rehearsal and
all previous negative results remain unchanged. Any recurrence can now identify
which hop/status/type failed, with safe evidence captured before restoration.
The next live step needs a specifically supported correction or explicitly agreed
validation scope, fresh IDs, current capacity reconciliation and a new model/review
allocation. One scoped external-review slot is not automatic permission to reuse
nd8 or fund another full qualification. No such spending was used here.

## Review artifacts and reproduction

- Committed plan: [actor-readiness-plan.md](actor-readiness-plan.md).
- Local source-bound JSON/Markdown/HTML:
  `.infra/benchmark-guard-harness/actor-readiness-probes-v1/` (`plan.json`,
  `observations.json`, `cleanup.json`, `result.json`, `assessment.json`,
  `report.md`, `report.html`, capacity snapshots and pre-restoration logs).
- Frozen plan SHA256:
  `221f86c457496fabc83278a37c9596ab694b2bbc3e162ab6a00b5061481fa605`.
- Deployment preservation proof:
  `.infra/benchmark-guard-harness/readiness-deployment-preservation.json`.
- MLflow experiment5 run `70d5152a9dd04988881ab23f873e8c2d`, artifact path
  `readiness-diagnostics`. This is CODE/infrastructure telemetry, not a paid judge.

Opening saved reports issues no model/tool/judge calls. The frozen batch is spent
and must not be repeated; a future non-effectful probe needs a new immutable plan
and output directory. Failed/incomplete probe execution returns a failing exit
status and cannot silently become environment acceptance.
