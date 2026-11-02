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
