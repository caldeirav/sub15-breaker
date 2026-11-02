# Laptop baseline and conditional server projections (nd2)

**Fixed laptop diagnostics completed; native validation is running. Server figures are projections, not measurements.**

- Protocol: [completion-first measurement plan](laptop-measurement-plan.md).
- Frozen matrix: `decee948301745520eaee4dcc295f359519d3afd02680c3dc19b2d434fbdbceb`.
- Device: Apple M4 Max,48GiB unified memory; classifier uses the unchanged MPS
  profile and frozen v1 checkpoint. Shared Qwen remains MLX4-bit/context8192.
- Image: `localhost:5002/breaker-banking@sha256:0e87927bc1efbe449deb94a70612693506d329fd0f7219b08383dd812403c894`.
- Actual store/Actor profile: `native-measure-v2`; model clients300s. Legacy
  histories, failed nd1 runs/review and all spending remain unchanged.
- Source: `e85a4d8`, control metadata `9b367ac`, ticket-lifetime correction
  `b0e3e57`. All563 tests pass on Python3.11–3.13.

The first image rollout rejected the longer ticket lifetime before freeze or
inference. The failure logs are retained; the corrected store starts under every
declared profile. No database, key or spending reset occurred.

Results will distinguish first observed from subsequent samples, minimum observed
from median/p95, reviewer time from native claim/tool-inclusive time, and model
correctness from enforcement/readiness. A timed-out request is not a completed
latency sample. A laptop minimum is not a guaranteed latency or optimized ceiling.

Server numbers will be conditional stage-scaling scenarios, not H100 benchmarks
or evidence that the same complete pipeline automatically becomes10x faster.
The production deployment itself has not been run or authorized by this test.

## Completed unoptimized baseline

MLflow run `2e0ce87090ce44f98ab5e7c8ca8b9a75` (experiment5).
Output: `.infra/benchmark-guard-harness/laptop-measurement-df9116f30221475d9f4ab74d1290c418/`.
Eight/eight model probes completed, with reconciled physical gateway calls and
provider idle; twelve/twelve encoder forwards completed. No optimization,
response repair, fallback or hidden warmup. All six LLM reviews allowed the
released benign actions; all twelve classifier reviews also allowed them.

| Same-input review | Classifier first input use ms | Classifier subsequent minimum / median ms (n=5) | LLM subsequent minimum / median ms (n=2) | Ratio of subsequent medians |
| --- | ---: | ---: | ---: | ---: |
| Read |341.071 |19.414 /21.262 |378.803 /387.312 |~18.2x |
| Full-prefix payment |35.824 |23.858 /24.964 |367.958 /386.816 |~15.5x |

These are small, fixed descriptive samples with unequal sample counts, not a
load-test or matched-safety guarantee. Every sample, including first use, remains
in the artifacts. Occurrence-paired comparisons are also recorded separately;
the table's ratio of subsequent medians is not presented as an individual pair.
First LLM reviews were719.726ms (read) and680.903ms (payment). Acting-model
transport probes were6349.325ms then824.413ms; they proposed a read but executed
no tools, so they are not acting-agent utility results.

### Where time goes

The classifier's subsequent encoder-total median (tokenization, device enqueue,
forward and host result) was **12.454ms read /16.538ms payment**. The corresponding
forward/host-result medians were11.271ms /15.035ms. Full review medians were
21.262ms /24.964ms: non-forward work and instrumentation are material.

Thus a short read's measured encoder stage is below15ms, but the complete review
is not; the payment encoder total is also above15ms. Native admission/claim is
another boundary and must not be replaced by these numbers. The local LLM review
was~0.39s subsequently, not universally>1.5s. The demo should show the observed
speed advantage without exaggerating the LLM baseline or hiding first use.

## Conditional server sensitivity, per input

Projection applies a factor only to the observed forward/host-result stage and
optionally a separate host factor to the remainder. Same frozen classifier,
same inputs/precision, resident batch-one serving; no hidden TensorRT/FP16 change.

| Assumed forward improvement | Assumed remaining-host improvement | Projected review median read / payment ms |
| --- | --- | ---: |
|2x |unchanged |15.627 /17.553 |
|5x |unchanged |12.198 /12.974 |
|10x |unchanged |11.012 /11.447 |
|2x |2x |10.631 /12.482 |
|5x |2x |7.250 /8.013 |

**The factors are assumptions, not measured H100 performance or confidence
intervals.** Under a5x forward-stage assumption with unchanged host overhead,
whole-review improvement is only~1.7–1.9x—not5x. These estimates exclude native
transport/auth/store overhead. A server could plausibly move this model-only
review below15ms, but the numbers do not demonstrate it or certify full native
admission latency. GPU/software utilization, network placement and queueing still
require measurement on the actual server. Qwen/MLX would additionally need a
separately qualified CUDA-serving equivalent; its speedup is not estimated here.

## Native validation is a separate gate

After the successful measurements, nd2's first native allow control returned an
application-level claim failure before tool dispatch. The reviewer allowed, but
the Actor could not claim the ticket; the case ended `unknown`, not prevented or
successful. State/fingerprint, zero tool attempts, cleanup and automatic
reconciliation were retained. Source:
`.infra/benchmark-guard-harness/native-demo-ff8d80dd75574c9b912b376f8b47018c/`.

The Actor had retained only the exception type. A safe allowlisted claim-error
code is now exposed and copied into action evidence. `nd3` is a native-only fresh
continuation with new source/image binding, no repeated diagnostic samples and
the same remaining120-local/17-review allowance. The nd2 control stays failed;
the model-only performance results do not establish that native demo acceptance
has passed. Native admission/claim measurements and five-card readiness will be
reported only from actual validated executions.
