# Human review: Actor-backed synthetic banking

**Human acceptance is pending.** Requirements/budget approval and independent technical review are not acceptance of the completed implementation. This review covers the controlled Actor service, external transactional state/receipts, durable evidence and opt-in agent adapter. It does not approve financial policy, a general gateway A/B boundary, production transport/key management, HA, model calibration or latency claims.

**Interim handoff:** the owner subsequently requested a PR for the existing work and a new architecture sprint, with remaining problems carried into issues. A draft handoff is explicitly authorized in [block-03b.json](block-03b.json) and [#29](https://github.com/caldeirav/sub15-breaker/issues/29). That direction does not turn the failed live run or pending manual review into a pass, and does not authorize merging this PR.

Delivery progress belongs in [roadmap #14](https://github.com/caldeirav/sub15-breaker/issues/14) and [#1](https://github.com/caldeirav/sub15-breaker/issues/1)/[#23](https://github.com/caldeirav/sub15-breaker/issues/23). The [service guide](../banking-actor-service.md) explains the technical boundary. Do not rerun paid validation merely to inspect evidence.

## Runtime evidence

Open [control run 649504e7c52c4f05ae39f1b8e5b96d2c](http://localhost:5001/#/experiments/3/runs/649504e7c52c4f05ae39f1b8e5b96d2c), experiment `breaker-banking-actor-service-03b`.

- `protocol.json` declares exactly 23 controls, including intentional crashes; no model/judge calls.
- `summary.json` reports the full runtime-control gate, not human or financial-policy acceptance.
- `runtime/*-assignment.json` binds actual running gVisor assignments to worker/Actor UIDs and runtime log messages. Desired WorkerPool configuration alone is insufficient.
- `runtime/*-probe.json` must show UID/GID **10001**, effective capabilities **0000000000000000**, `no_new_privs=1`, no ambient Kubernetes token, and only expected private sandbox mounts.
- `audit/case-trace-score-readback.json` maps each case to its exact trace. Each `runtime/passed=true` must have a unique root **CODE / banking-actor-service-v1** source.
- `audit/outbox-readback.json` maps durable events to persisted traces. Both `runtime/event_kind` and the actual boolean `runtime/durable_event=true` must match, with unique CODE ownership. Numeric 1 is not a substitute for boolean true.
- `audit/post-review-strict-readback.json` records stricter post-review validation without inventing new executions; backend source snapshots and deployed image/template must remain bound.

The matrix has 14 claimed tool attempts and 13 committed results. The extra claimed attempt is the intentionally interrupted pre-commit case, not a hidden successful write. Transport rejections and claimed attempts are different denominators.

## Inspect representative controls

| Case | Trace | Expected observation |
| --- | --- | --- |
| `valid_send_money` | `tr-752e0ad234005a155df25794843b1fba` | A real **synthetic** tool result/receipt; `executed=true`, `fixture_only=false`, changed state/version, and `financial_authorization=false`. No real money moves. |
| `valid_update_password` | `tr-9950872a57e310b51a5c1cd8d95e25a0` | Password withheld, but authoritative change flag/version/fingerprints still show the mutation. Redaction must not erase this fact. |
| `idempotent_replay` | `tr-992859fd2c22de4113a95b85be478572` | Original receipt returned; no second effect or version advance. |
| `changed_payload` | `tr-8fbf154e0cda4dc03646124e307ce15b` | Same ID with changed arguments rejects `action_id_conflict`. |
| `stale_state` | `tr-3c69ce258b3487c51b0e5da4900ba82a` | Stale optimistic state rejects `stale_state`. |
| `cross_trial_binding` | `tr-3dd6499b10fa67dd5135be8f0ee7a985` | Wrong Actor cannot claim the other trial's ticket; the correct Actor succeeds as a healthy positive control. Initial-state equality does not mean state is shared. |
| `fresh_actor_reset` | `tr-71c3bad9b9889e37a9286f2f1c572399` | Different actual Actor UID, generation 1 → 2, state version restored to 0, original keyed fingerprint restored and old completed receipts retained. |
| `stale_generation` | `tr-51001abfa932bf56aaa877d79d422bf1` | New Actor cannot execute an old-generation ticket: `actor_identity_mismatch`. |
| `store_pod_restart` | `tr-4b85ed87ba424df04e264afb34f9ddd2` | Owned store pod restarted; state and historical receipts survive on the dedicated PVC. This is not a node/disk-loss test. |
| `mlflow_outage_outbox` | `tr-4e9e08188ba764c0c84d263e80cfb929` | The exporter's tracking connection is deliberately refused; evidence stays pending/unchanged, then uploads and verifies after recovery. The shared MLflow server is not stopped. |
| `crash_before_commit` | `tr-599bdc6ed4aa529c6274a64c405ec85a` | Dedicated Actor exits after claiming, before tool computation/commit. Execution stays unknown, no result is fabricated and authoritative state is unchanged. Cleanup fences the unresolved attempt. |
| `crash_after_commit` | `tr-2115697fef6cfd23a9570bfe1bdf3c6c` | Actor exits after durable commit but before returning its response. Status lookup recovers the committed receipt/version; matching replay does not execute again. |

Unlike the earlier record-only fixtures, `executed=true` here describes an actually invoked synthetic tool with committed evidence. It does not mean settlement, financial authorization or completion through the future gateway verifier. Red/error child spans in intentional crash/rejection controls are expected; compare the declared stage, receipt, state and outcome instead of requiring every span to be green.

## Live-agent evidence and paid budget

The owner-authorized live budget was consumed once: three local-model trials and twelve native Gemini criterion reviews. [Run f3d8498e82f94d7aadd36404e34c829b](http://localhost:5001/#/experiments/3/runs/f3d8498e82f94d7aadd36404e34c829b) remains **FAILED / passed=false**, despite complete trace/outbox audit and 12/12 valid, agreed reviews. The failure is not a 3/3 utility requirement: the rent trial encountered an unexpected local serving error before receiving its update call. The predeclared non-fault live gate has not been waived.

Review verdicts are **8 satisfied / 4 insufficient_evidence**, not twelve satisfied outcomes. The errored rent trial's inconclusive reviews are retained, while upstream utility stays false. [Independent source/evidence review](block-03b-independent-review.md) is separate from overall acceptance.

| Live case | Trace | Observed result |
| --- | --- | --- |
| Bill | `tr-f58140a86cdbbe91bed317405bbeba91` | completed, utility=true, 3 model attempts / 2 Actor tools |
| Rent | `tr-9e4660d57148a326a74647af03b35661` | error, utility=false, 4 model attempts / 3 successful Actor tools; final local model request returned HTTP 500 |
| Address | `tr-10b50f6176e96d69ec34a0453e4e50c0` | completed, utility=true, 3 model attempts / 2 Actor tools |

`audit/local-provider-diagnosis.json` identifies the local server parser error: missing closing `</tool_call>` at index 127. The malformed response never became a structured call received by the adapter; no rent update was dispatched. All 71 durable events reconcile: three trial creations/fences, ten model attempts with nine results and one error, seven preparations/tool attempts/results and twenty-four judge attempt/result events.

The owner then authorized exactly one diagnostic-only replay. [Run 0009aa95aee848bab7bae3dce0a9524e](http://localhost:5001/#/experiments/3/runs/0009aa95aee848bab7bae3dce0a9524e), trace `tr-4413aa3343223cf08070dcb85581f6ec`, reproduced the same parser HTTP 500 with one local inference, zero banking-tool execution and zero Gemini calls. Public schema declarations withheld by secret-field redaction were restored from the same pinned catalog; other message values were not reconstructed or changed. This is diagnosis, not a replacement task attempt or a successful rent outcome. Track resolution in [#28](https://github.com/caldeirav/sub15-breaker/issues/28); no further budget is implied.

Inspect each live trial's AGENT root, actual CHAT_MODEL requests/responses, remote TOOL spans and independent receipts. Canonical amount schemas are decimal strings; no float coercion or evaluator solution is supplied as admission context. Follow native Gemini review traces back to their exact target/criterion and inspect their scalar citation/agreement/error scores. Agent utility is an observed outcome, not a required universal win.

The full live summary must not say passed until its exact trial/review matrix, trace audit, cleanup and durable outbox export/readback pass. Source controls must identify the same observed ready image/template used for live calls. A provider setting for OpenAI/Anthropic must not consume a budget authorized only for Gemini. Existing budget reservations are retained even after failure; no resampling for preferred answers/agreement.

## Scope and acceptance report

Inspect the restored root README as project context/architecture/rationale and usage. Implementation status and block sequencing are on GitHub, not a README release ledger.

Report your handle, review date, inspected runs/cases and findings, or explicitly accept this controlled service scope. Preserve all failed runtime attempts and diagnostics. Do not reuse prior acceptance or relabel an unknown outcome as prevented execution. The owner-authorized draft handoff is a specific publication exception; it is not full release acceptance or a general waiver for subsequent PRs.
