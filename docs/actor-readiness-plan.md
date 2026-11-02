# Actor readiness investigation — #62

PRs #57 and #61 reviewed with green Python3.11–3.13 CI and609 local tests,
then merged into main as `0619128` and `a3b75db`. Delivery is not demo acceptance:
#45/#48 stay open. All original qualification/rehearsal outcomes remain immutable.

## Initial scope: no inference or banking effects

1. Add bounded boundary-specific RuntimeClient diagnostics: HTTP status, known
   media type, bounded body length/digest, elapsed time, safe operation ID and
   exception category. No raw bodies, URLs, credentials, banking payloads, repairs
   or automatic retries. Retain Actor→store and driver→Actor hops separately.
2. Test non-JSON/empty/truncated/oversized responses, auth rejection, connect/read
   timeout, nested diagnostic sanitization and structured logging/cleanup. Same
   strict request parsing, verified identity and native fail-closed behavior.
3. Deploy diagnostic image with unchanged256 store limits, PVC/key/history and
   existing capacity reservation. Verify preservation before any Actor probe.
4. Freeze one four-Actor/eight-readiness-call probe batch. Each Actor has one first
   observation and one explicitly declared subsequent observation; neither is a
   retry replacing the other. Match failed rehearsal's native control hook2s.
   Readiness calls prepare/claim/execute nothing; no /create/trial or model calls.
   Complete all fixed diagnostic observations even on read failures; stop on unsafe
   cleanup/resource contradiction. Capture diagnostics and egress logs BEFORE hook
   restoration, keep every observation and verify store/ledger unchanged.
5. Diagnose only what evidence supports. Passing probes are not retrospective
   causal proof. If an actual correction is supported, add focused regressions and
   a separately declared bounded verification batch. No model-backed qualification
   or rehearsal until correction/configuration and fresh allocation are agreed.

The old nd8 first-case failure stays failed, never reused. One scoped external
review slot remains; this work spends none. Presentation capacity is not model
authorization. No shared-model reload, classifier/prompt/threshold change, auth
bypass, frontend implementation or generic executor. #55/#13/#56 stay deferred;
#60 remains visualisation planning-only. Preserve/update the existing read-only
review package rather than silently replacing old evidence with successful probes.

## Initial executed bindings

Source `4589899`;622 tests passed Python3.11–3.13 before deployment/probes.
Diagnostic image:
`localhost:5002/breaker-banking@sha256:19f625ed48a7c5be2e54429284a390108ba659df5bb93965b9858a974860174d`.
The same PVC/key, every existing table row and active capacity reservation were
verified unchanged across deployment. Trial limit256 and profile
`native-measure-v2` remain unchanged; only transport diagnostic behavior was added.

The initial fixed plan is
`.infra/benchmark-guard-harness/actor-readiness-probes-v1/plan.json`.
It binds source hashes/image/configuration and permits four Actor allocations,
one first and one subsequent readiness observation per Actor, zero model/tool/
judge calls and zero trial creations. Started markers prevent replay of the batch.
Results and pre-restoration logs will be retained in that directory, without
overwriting nd8's failed case or spending its unused allocations.

## Observed result

The fixed batch completed8/8 verified readiness responses; both hops were200/JSON.
Ledger, history, capacity and hook restoration checks passed, with no remaining
Actors and no trial/model/tool/judge calls. The old failure did not reproduce;
cause remains unconfirmed and #62 stays open. See [results](actor-readiness-results.md).
