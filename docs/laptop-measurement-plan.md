# nd2: completion-first laptop measurement and native validation

Owner direction: allow requests to complete and measure the unchanged baseline
before optimization. Retain nd1 failures and all spending. The classifier is an
accepted stand-in for a decision model; no retraining, new weights, precision
change, provider fallback, global LM Studio setting change or weight reload.

## Frozen execution allowance (maximum, not actual spend)

Fresh namespace `nd2`, original combined v4 ledger, cumulative2048 local /512
external /$100 caps. Per-phase maximum128 local requests and17 Gemini operations:

- Eight independent model diagnostics: two identical first-turn actor transport
  probes, three identical read-review probes, three identical full-prefix payment
  reviews. Each has its own one-request ID. No tools execute in these diagnostics;
  they are not genuine agent utility cases. Errors are retained and the fixed
  diagnostic list continues; no request is automatically retried.
- Twelve declared classifier forwards: six per identical input (read/payment),
  interleaved. Record all samples; report first input-shape use, subsequent five,
  minimum observed, median and small-sample p95. There are zero hidden warmups.
  The shared LLM was already loaded: first observed is not proof of cold weights.
- Existing native controls, learned canary pair and six real-backend card cases:
  up to120 local requests. D01/D03 are genuine acting-agent flows, D02 is the
  released scripted proposal after its legitimate prefix, D04/D05 are faults.
- Up to16 task reviews and one scoped harness review. If execution is incomplete,
  an explicit incomplete review keeps every missing declared native case required.

## Completion-first deadlines (seconds)

New opt-in profile `native-measure-v2`:

| Boundary | Budget |
| --- | ---: |
| Acting model / LLM reviewer client |300 |
| Model backend / model route |315 /330 |
| Native hook |330 |
| Actor store claim |350 |
| Tool worker, reap allowance, commit |15 +5 +10 |
| Actor server / client |390 /410 |
| MCP backend / client / route |430 /450 /470 |
| Prepared ticket |900 |
| Episode wall-time |3600 |
| Post-run evidence/provider reconciliation |120 |

The Actor server covers claim+worker+commit+response allowance. The separate
gateway model route and backend budgets are raised temporarily on owned resources
and restored; increasing just the client would leave a hidden60s route cutoff.
Auth, model selection and retry policy stay unchanged. Native timeout faults
still use a declared2s hook. Legacy/nd1 profiles are not rewritten.

These are investigation allowances, **not target latency**. They cannot guarantee
completion if a provider hangs. A timeout remains an error/censored observation,
never a successful speed sample. Diagnostics continue to gather independent
evidence; effectful native cases remain gated on resolved safety/telemetry facts.

The first image rollout exposed the store's old90s maximum ticket lifetime and
failed before matrix freeze or inference. Logs are retained under
`.infra/benchmark-guard-harness/nd2-rollout-diagnosis-407b574c3250468eaf37801744865f12/`.
The store maximum is now a bounded900s, with its30s default unchanged; constructor
tests cover every declared profile. No database reset or spending reset is used.

## Sequence

1. Offline regressions and exact diagnostic-input digest checks.
2. Commit source; rebuild digest-bound Actor image; deploy/verify actual profile.
3. Freeze the new matrix and exact allocations before inference.
4. Run `--phase nd2 --stage diagnostics --execute-demo`: eight fixed model probes,
   then twelve classifier forwards, recording startup/resources/hardware.
5. Run fresh controls, full-prefix native canaries, then D01/D02/D03 pairs, once
   each. No preferred-outcome sampling. Errors, unknowns and model mistakes remain
   separate from enforcement mechanics and readiness.
6. Reconcile receipts/effects/physical calls, publish comparisons and reviews.

All commands use `src.benchmark.demo`; `--freeze-demo --phase nd2` binds the new
matrix. Do not reset nd1 IDs or use its consumed review slot.

## Production-server estimate

First measure laptop stages. Then publish **conditional sensitivity estimates**:

`projected review = forward/host-result / GPU factor + remaining adapter / host factor`.

Use GPU factors2/5/10 and host factors1/2, per input. They are assumptions—not
H100 measurements or a promise. An H100-class resident batch-one deployment is
an example target ([vendor reference](https://www.nvidia.com/en-us/data-center/h100/));
peak hardware specifications do not establish this checkpoint's latency.

Keep native transport/auth/store overhead outside the model estimate. State what
model-stage speedup would be needed to reach15ms and when host/network overhead
prevents it. Do not assume CUDA/optimized precision/compilation while calling it
the same unoptimized setup. Production load/queueing and remote network hops can
make latency worse despite faster hardware. Actual server qualification is a
separate deployment and measurement, not authorized by this laptop run.

These projections concern the PyTorch classifier path. Qwen's current MLX4-bit
serving stack is Apple-specific; an NVIDIA deployment would require a separately
qualified equivalent model/quantization and CUDA-serving backend. Do not transfer
the laptop classifier/LLM ratio unchanged to a server, or treat that backend port
as the same measured deployment.

## Native continuation after successful measurements

All eight nd2 model diagnostics and twelve classifier forwards completed. The
first native allow control then returned an application-level claim failure
before any tool dispatch. Its trace/state/reconciliation are retained; the
Actor's response had discarded the safe ContractError code and kept only its
type. A safe allowlisted claim-code field is added for diagnosis.

`nd3` is the fresh native-only continuation: the same remaining120-local /
17-review allowance, new image/code binding and fresh native IDs. It contains
**no** diagnostic or encoder-measurement cases; successful nd2 samples are not
repeated. Total user-authorized local allowance stays8+120=128. The failed nd2
allow-control ID is not reset or relabelled successful. No broader IAM relaxation,
JWT bypass or alternative guard is introduced to get a green result.
