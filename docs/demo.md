# Five-card live demo UI and operator runbook

[Local setup](infra.md) · [Agent flow](agent-flow.md)
· [Validation](validation.md) · [Latest versioned results](results/demo-ui1.md)

## What is demonstrated

The demo shows Substrate enforcing the selected reviewer's effective decision on
the exact prepared action, with independent dispatch, receipt, state and trace
evidence. It is curated architecture evidence, not general model accuracy.

| Card / selector | Producer and guard | Required target outcome |
| --- | --- | --- |
| D01 `pay-bill` |Genuine task0 agent; classifier or LLM |Bill read then intended payment, one target effect/receipt, original utility |
| D02 `deny-extra-transfer` |Released scripted task0 prefix + `injection_task_0`; classifier or LLM |Legitimate prefix remains; **zero additional target** transfer/receipt |
| D03 `update-profile` |Genuine task13 agent; classifier or LLM |Read supplied address, requested update with original utility/state/receipt |
| D04 `reviewer-error` |Declared deterministic fault control |Effective error denies claim, zero target computation/effect |
| D05 `cancel-late-allow` |Declared cancellation fault control |Late allow discarded, trial fenced, zero later target mutation |

Six native controls and two complete-prefix real-reviewer canaries are prerequisite
gates. The live UI creates two fresh lanes per click, including independent
fault controls. First-session setup has eight native cases; running all five cards
once produces **18 native cases**. Cards can then be repeated without allocations.
The older CLI
qualification/rehearsal protocol below has14 cases because it reuses the shared
error/cancel control records for D04/D05. Neither count is a model-accuracy
denominator. D01–D03 real guards review every prefix action. Rent remains outside
these cards but in the full test and known quality limitation #55. A denial is
terminal in every card: there is no retry, override or human-escalation path in
the demo, although Agent Substrate supports one
([#74](https://github.com/caldeirav/sub15-breaker/issues/74)).

## Live web interface — end to end

The primary UI is **live execution, not saved replay**. Choose a card on the left
and click **Run both routes**. The classifier and LLM lanes appear side by side,
but run **sequentially** because both acting agents and the LLM reviewer share one
Qwen server. The order is fixed/displayed for each run and counterbalanced across
cards and repeats. Only one pair may run at a time. There is **no campaign,
allocation, spending budget or per-card run count** in the live UI.

### Prerequisites and first-time setup

1. Clone the repository, install Git, uv and Python3.11–3.13, then
   `uv python install` and `uv sync --locked`. No Node/npm build is needed for the
   application; FastAPI/uvicorn serve local HTML/CSS/JavaScript with no CDN assets.
2. Follow the [complete local infrastructure guide](infra.md): a reviewed rootful
   Podman VM, owned Kind/Cilium/Substrate/gVisor installation, enforcement Gateway,
   digest-bound banking store/Actor image, `native-measure-v2` profile and explicit
   retained-trial limits. A manifest or controller install alone is not readiness.
3. Obtain the **compatible frozen classifier export** from the operator, under
   `.infra/benchmark-guard-harness/modernbert-training-v1/model`. Weights/credentials
   are not published or generated automatically from a checkout. The demo does
   not require a benchmark ledger. Base/random weights are not substitutes for
   the trained artifact. For a genuinely new release/profile, initialization
   and artifact distribution still require explicit operator provenance (#10).
4. Create `.env` from `.env.example` only if absent. Set the exact approved
   `LM_STUDIO_MODEL=qwen/qwen3-30b-a3b-2507`, local provider port1234, HTTP MLflow
   port5001, and the authorized Gemini2.5Flash credentials/profile. This live UI
   includes paid external review and sends projected synthetic evidence externally.
   Never connect real banks, real payment credentials or a shell executor.
5. Manually start LM Studio and load the approved cached model with context8192.
   Start MLflow once with the [documented backend/artifact paths](../README.md#run-locally)
   if this installation has no tracking database yet. Use the restart launcher
   below on the existing installation. For **service-only/manual** management:

```bash
bash scripts/demo_stack.sh start
bash scripts/demo_stack.sh status --json
```

The service manager resumes only owned installed services, checks the model without
generation and renews scoped driver credentials. It does not start a live case,
prime the classifier or run Gemini. It will not download/build a missing stack or
replace old data. Use the setup guide, not `destroy`, to resolve prerequisites.

### Restart after a reboot — one command

**Setup once, restart many times.** The launcher uses the existing installation;
it is not an installer and never builds images, creates a VM/cluster, downloads
models, resets a store or replays historical work. A new installation still needs
steps1–5 above, including banking deployment **before** managed route setup. An
older installation needs the explicit [store upgrade below](#one-time-upgrade-of-the-existing-banking-store)
only if repeatable-demo mode is not already installed.

Enroll the installed configuration once (metadata verification only):

```bash
# Preserve the existing file/credentials; make it private if needed.
chmod 600 .env
bash scripts/run_demo.sh --setup --provider-config user \
  --machine podman-machine-default
```

`--provider-config user` explicitly records `~/.config` and `~/.local/share` for
the stack's tool environment. Use `current` instead for an intentionally
customized XDG installation. This resolves inherited alternate-XDG discovery
without changing your shell, global configuration or default Podman connection.
The selected connection must already match the owned cluster fingerprint. An
empty machine/connection list is **not** permission to recreate the installation.

The private `.infra/demo-stack/installation.json` records the approved existing
machine identity, provider roots, versions, metadata/artifact hashes, local
endpoints and retained tracking-storage identity. It authorizes starting that
existing VM only; **LM Studio and its model remain check-only**. No secret values
are stored in the profile. A changed image/model/version/storage/profile fails
closed. After an intentional reviewed upgrade, archive the old installation
profile (do not remove lifecycle `state.json`) and explicitly enroll again.
The current serving pin is MLX **1.14.0**, owner-approved for issue68; older
1.13.1 results remain historical, not automatically requalified.

After a reboot:

1. Start LM Studio and its HTTP server yourself; load the exact cached Qwen
   MLX4-bit model with context8192. The launcher checks the app **and mapped
   runtime**, loaded model, context and idle status; it never starts, unloads,
   reloads or changes shared model settings. Busy/unobserved state is a blocker.
2. Run **one command** from this checkout:

```bash
bash scripts/run_demo.sh             # serve UI; no startup inference
# OR, explicitly do real local preparation before serving:
bash scripts/run_demo.sh --prepare
```

Both modes validate the existing locked Python environment without syncing or
installing. Independent configuration/model/provider/port/asset blockers are
reported before starting services. The launcher starts the recorded stopped
rootful VM, resumes immutable owned registry/Kind containers, starts or borrows
compatible MLflow, waits for installed Kubernetes/service rollouts, renews driver
JWTs, verifies repeatable mode/routes/host-forwarding address and quiescence,
then serves **http://127.0.0.1:8091**. No saved replay service is required.
Progress is printed while rollouts wait; the per-stage timeout defaults to180s
and is recorded at enrollment. There are no automatic inference retries.

**Readiness is deliberately distinct:** enrollment means installed/configured;
service readiness means dependencies only; UI-listening means the page is
available; **Demo ready** means actual local preparation succeeded. Without
`--prepare`, the first explicit Run click performs preparation. With it, the
existing probes/priming, six native controls and two canaries create synthetic
setup evidence, but no D01–D05 card and **no Gemini call**. Gemini2.5Flash is
pinned by the live runtime, not overridden by `MLFLOW_GENAI_JUDGE_DEFAULT_MODEL`;
its credential is checked for presence only, not validated through a paid call.
`LITELLM_LOCAL_MODEL_COST_MAP=True` defaults before runtime imports.

Unlock using the separate private `.infra/live-demo-ui/ui.token` file; the
launcher prints its location, never the capability. Private service logs are in
`.infra/demo-stack/logs/`, launcher phase in `.infra/demo-stack/launcher-status.json`,
and UI/preparation evidence in `.infra/live-demo-ui/sessions/`. The terminal
remains the UI supervisor. Navigation/unlock/status never run a card.

```bash
bash scripts/run_demo.sh --status    # read-only JSON; no inference or renewal
```

A stopped VM blocks downstream checks explicitly rather than producing unrelated
Kubernetes failures. Status does not equate a listening UI with prepared readiness.
While the UI owns its session, status reports `ui_listening` or
`startup_or_cleanup` and defers independent checks: temporary UI-owned templates
and a legitimately busy model are not misdiagnosed as installation drift. Check
the UI's own preparation panel for **Demo ready**.
The launcher holds lifecycle and UI locks for its entire session: a second
launcher/service start/stop cannot mutate routes underneath it, and a direct UI
cannot race startup. Stop the UI with **Ctrl-C**, allow active work/reconciliation
and native-hook restoration to finish. Services are retained for quick reuse.
Only afterwards, optionally run `bash scripts/demo_stack.sh stop`; it stops only
manager-owned resources and always preserves borrowed services, VM, LM Studio,
database/PVC/receipts/artifacts/history. The VM is never automatically stopped.
VM helpers, in-flight infrastructure commands and owned port-forwards use
separate process sessions so terminal Ctrl-C cannot kill dependencies before
final evidence readback/restoration. A cleanup error is retained in the private
session's `cleanup-failure.json` and propagates as a launcher failure, not success.

Host boot identities distinguish a real reboot from PID reuse. After a proven
reboot, prior ownership records are archived in `.infra/demo-stack/recovery/`;
immutable container IDs are reverified, externally auto-restarted containers are
**borrowed**, not claimed for shutdown. Legacy process records are upgraded only
after their live PID/start/command matches. Same-boot external restarts, ambiguous
interrupted starts, replaced IDs and legacy reused PIDs still fail closed: inspect
the retained private records, do not delete state or broadly adopt/kill resources.
A failed/partial startup retains ownership/logs for inspection and safe service
stop; it does not blindly roll back data or fence Actors. A changed host-forwarding
address requires reviewed route reconfiguration and re-enrollment, not automatic
route replacement. Functional startup is not the two-hour reliability claim (#39).
See [issue68 startup/shutdown validation](../validation/demo-restart-68.md) for actual
test outcomes and the remaining physical-reboot acceptance check.

### One-time upgrade of the existing banking store

The old banking image enforced retained-trial/action limits as well as reserved
campaign slots. Rebuild and enable **repeatable demo mode** once on the existing
installation, with the UI stopped and no Actors or unresolved actions:

```bash
bash scripts/build_banking_image.sh
uv run --locked --env-file .env python -m src.banking_service.deploy \
  --image "$(cat .infra/banking-service-03b/image.reference)" \
  --deadline-profile native-measure-v2 --repeatable-demo
```

This reuses the owned store key/PVC and all prior trials/actions/receipts. Previous
capacity reservations are marked released with used counts retained; no history
or budget files are deleted or reset. The mode removes retained trial/action caps
and does not create any new reservation. The ordinary benchmark/store default is
still bounded; its historical policies/ledgers are independent of this demo.

If image building fails with `dns error` / `failed to lookup address` while
downloading a wheel, the failure is Podman build-network DNS, not a missing
package or a model error. Retry the build when connectivity recovers; downloads
use reduced concurrency and bounded transport retries with the lock/TLS intact.
For a persistent VM/VPN resolver problem, supply a reachable DNS server permitted
by your network with `BANKING_BUILD_DNS=DNS_SERVER_IP bash scripts/build_banking_image.sh`.
`UV_CONCURRENT_DOWNLOADS=1` can further reduce concurrent download pressure. No
global resolver changes, public-DNS substitution or cluster/Actor egress changes
are made automatically. Do not delete the database, lockfile, VM or cluster.

The demo has no artificial run-count or spending limit. Physical disk capacity,
provider quotas, per-episode model/tool/time limits and unexported-evidence outbox
backpressure still apply. Gemini is **not free**: every new run performs real
post-run external reviews with normal provider charges. Usage observations are
recorded for transparency but never debit or enforce a demo budget.

### Start the UI and run a selected card

```bash
uv run --locked --env-file .env python -m src.demo_ui
```

### Prepare before the audience arrives (recommended)

Stop any existing UI gracefully, then launch the same server with `--prepare`:

```bash
uv run --locked --env-file .env python -m src.demo_ui --prepare
```

This explicitly runs service/model probes, resident classifier loading/priming,
the six native controls and two learned-reviewer canaries **before the web UI
starts accepting requests**. It can take several minutes. Wait for the terminal
message **`Demo ready — startup checks complete; presentation cards have not been run.`**
and the server URL, then open the browser. The UI also reports **Demo ready**.

Preparation uses the same persistent worker/classifier/native hook and the same
checks as first-click startup; it does not bypass them, run D01–D05, consume a
presentation run ID, change arm order or invoke Gemini. It does make real local
Qwen probe/canary requests and creates the normal synthetic setup trials/receipts.
Its separate events/status are saved under the session's `preparation/` directory;
native source/startup records remain in `runtime/`. On failure the UI is not
served, failed evidence remains, owned cleanup/restoration runs, and no automatic
retry or card execution is performed.

**Keep this server and LM Studio running.** Every later Run click reuses readiness
and skips the startup gate; browser refresh is fine. Stopping/restarting the server
requires preparing again. This moves setup before the presentation, not ordinary
agent/tool/Gemini latency out of each card, and it does not guarantee latency after
long idle periods. Without the flag, existing first-click preparation is unchanged.

Open **`http://127.0.0.1:8091`**. Read the separate local **UI run capability** from
`.infra/live-demo-ui/ui.token` and enter it in the unlock form. This is not the
saved-replay token and never a provider/platform credential. It is private0600,
held server-side after sign-in through an HttpOnly/SameSite=Strict session cookie;
Run POSTs additionally require same-origin and a per-session CSRF value.

Opening, signing in, selecting cards, reconnecting or paging events never starts
inference. Each explicit Run click creates fresh unique IDs for both lanes. Without
`--prepare`, the first click verifies actual gVisor/Actor identity and performs the
functional model probes and two fixed unlabelled classifier priming passes, then
runs the native controls/canaries. It keeps the classifier
resident on the measured worker and installs one native hook/bridge for the UI
session. The same compiled agent/native store path is reused, not a second loop.

During this first-run gate, both lanes show **Startup**, including the latest
observed step and native-check count, and the startup-observations panel opens
automatically. This gate can take several minutes before either measured route
starts. A startup failure is shown as a failed/not-completed run, not perpetual
waiting. Once a route starts, its panel shows Running until final evidence is
reconciled; the other route explains that it is waiting for sequential execution.

One arm runs, is fenced/cleaned up/reconciled, then the other runs on equivalent
fresh state. Scoped driver authority is renewed before each arm so an idle pause
does not blindly reuse expired credentials; renewal never runs a model or replays
an action. There is no concurrent acting-model/reviewer load from the two lanes,
backend substitution, response repair or automatic retry. A browser disconnect
does not cancel or rerun a payment; reconnect reads the existing active job.
After completion, click Run again for a **new recorded run**, as often as needed.
Earlier failures/results remain separate and unchanged. Duplicate requests reuse
the same job, including after a server restart. Interrupted jobs are marked as
such and never automatically rerun. After a runtime/cleanup failure the server
halts further dispatch: inspect evidence, shut down gracefully and restart after
fixing the underlying problem. Fresh startup then checks real quiescence/readiness
before creating any work; it cannot ignore leftover Actors or unresolved actions.

Execution-code changes require a graceful server restart before a new run;
runtime source integrity is checked between arms. Browser-only HTML/CSS/JavaScript
updates remain recorded in the protocol but do not abort native execution. If a
run fails between arms, the finished lane stays completed, the interrupted lane
is marked failed, and a safe known reason (such as restart required) is displayed
instead of leaving the lane looking active. Unknown raw exception text is never
exported to the browser.

### Interpret the display

- **Use-case context and expected outcome:** each card shows the actual pinned
  task prompt, a masked view of the starting synthetic state and its untrusted
  documents, the pinned tool inventory, the released attack proposal for D02
  and the declared fault for D04/D05, plus the structured expected outcome
  (expected effective decision, golden invariants and what would violate
  them). Context is served read-only from the pinned adapter/plan data with
  its digest recorded in the session evidence; if that derivation fails, a
  labelled fallback shows only the curated short description and the static
  browser strings. Opening or selecting a card still never dispatches work.
- **Decision-model input/output:** after a lane finishes, each action's
  "Decision review" expander shows the exact masked projection the reviewer
  received (goal, policy, tool and arguments, untrusted observations, state
  view, token count, input digest) and what it returned: the classifier's
  decision, calibrated risk against the frozen threshold with the logit
  difference and temperature, and core versus whole-review latency; the LLM
  reviewer's decision, raw verdict JSON, prompt version and whole-review
  latency. Both routes review the same input for a given action digest; live
  SSE events stay terse and whitelisted, and these richer values appear only
  in the post-run summary. Fault controls label their input as the
  wiring-control projection with no model verdict.
- **Per-route component flow:** each route's lane keeps its own component-flow
  ribbon — the components its execution actually traversed (agent loop,
  agentgateway model/MCP routes, Qwen server, banking bridge, state store,
  Substrate gVisor Actor, native Envoy claim gate, reviewer, MLflow evidence)
  with traversal counts, accumulated live and **retained after the run**. Every
  timeline entry is tagged with the component that produced it from observed
  host events only (gateway spans appear after persisted readback); nothing
  fabricates remote internals. A collapsible legend on the routes heading
  explains each component's role and the transport-versus-execution
  distinction: agentgateway carries requests; Substrate's native gate decides
  whether the Actor may execute.
- **Paired final outcome:** each route shows a verdict banner (expected versus
  observed effective decision with executed/blocked/error counts), and the
  paired table joins actions across routes on the frozen input digest where a
  golden label exists — classifier decision, core ms and calibrated risk
  against LLM decision and whole-review ms, with per-route outcome and
  receipt. When the two agents proposed different actions, unmatched rows
  remain visible per route and never become a same-input speedup or accuracy
  claim. A deterministic card-level outcome statement summarizes the run.
- **Timeline:** actual observed agent proposals, managed model HTTP, MCP, native
  review, Actor/result, original golden check and cleanup events. Host observation
  times are not fabricated remote wall clocks. Exported gateway span durations
  become available after persisted readback; they are labelled as observations,
  not made-up live gateway internals. Complete source traces remain in MLflow.
- **Golden outcome:** original pinned utility plus target execution/receipt/state
  invariants. Matching frozen action digests can show their independent action
  label; a novel agent action is explicitly not assigned that label from utility.
  D02 is scripted released attack-proposal evidence, not agent attack-win rate.
- **Guardrail emphasis:** classifier decision core and both whole guard-review
  columns, then other component boundaries with exact n/median. Core is inside
  whole review, inside native claim, inside tool/MCP roundtrip. Do not add nested
  bars, claim a pure gateway/network/queue cost from inclusive spans or calculate
  model speedup on unmatched action sequences. Event/tracing overhead is real;
  it is outside classifier core but can occur inside inclusive adapter/admission
  boundaries. Slow after-readiness samples remain. Whole-guard medians use completed
  allow/block reviews; errors/timeouts remain in the event/source records and are
  not treated as successful speed samples.
- **Faults:** D04/D05 are independently executed controls for both labelled routes.
  They do not invoke real reviewers in their case path and show model-inference
  latency/risk as not applicable, not zero. Expected errors and discarded late
  allows are distinct from learned policy blocks.
- **Gemini judge evaluations:** the final evidence panel lists each
  task-criterion review per genuine route (D01/D03): what is evaluated (the
  versioned criterion rule), the golden data (pinned parameters such as the
  expected recipient/amount and the CODE-oracle expected verdict), the judge's
  verdict and whether it agrees with the golden expectation, with the judge's
  bounded rationale behind each row's expander. D02/D04/D05 show the scoped
  harness review only. Raw judge start/finish bookkeeping is no longer shown
  in the observation timeline. Review time/cost is outside guard performance.
  Errors, disagreement and negative verdicts stay visible and never overwrite
  CODE or human acceptance.

Both arms can be displayed together without being statistically identical: agents
may propose different calls, and shared-device idle/cache conditions still vary.
These are curated live observations, not a held-out safety or p99/SLO claim.

### Shutdown, evidence and API boundary

First Ctrl-C the UI and allow the active pair/review to finish and owned native
hook/routes to restore. Do not force-kill during a mutation. Then use
`bash scripts/demo_stack.sh stop` if needed; it refuses active native work and
leaves borrowed services, LM Studio/model, shared VM and data untouched.

Private UI evidence lives in `.infra/live-demo-ui/runs/RUN_ID/`: per-job `public.json`,
append-only `events.jsonl`, source-record hashes and raw review records. Session
startup/controls/source records and observation-only usage logs live under
`.infra/live-demo-ui/sessions/SESSION_ID/` and linked MLflow runs. IDs are automatic
evidence identifiers, not allocations or limits.
All failed/partial attempts remain. Public events omit credentials, complete bank
state, raw prompts and ticket capabilities; tool arguments shown in final panels
are bounded canonical/redacted synthetic values rendered as text, never HTML.

The loopback API under `/api/live/` has authenticated status, a read-only
card-context endpoint derived from pinned data, explicit Run POST,
repeatable run results and resumable SSE observations. It never accepts paths/prompts/commands
or browser infrastructure credentials. A single worker and operator lock serialize
the global hook/bridge and both arms. There is no arbitrary live cancel endpoint;
D05 is the declared cancellation scenario. API reads cannot issue inference. The
older [saved-review API](#read-only-backend-contract) stays separate and read-only.

### UI validation without spend

Default `bash scripts/test.sh` includes fixture-backed API, auth/CSRF/Host/body,
idempotency across restarts, repeated runs, sequential scheduling, events, failure,
usage-journal isolation and repeatable-store tests. The
explicit `validation.live_ui_fixture_server` and `validation.run_ui_browser` are
**offline UI test fixtures**, never the real demo or a fallback runtime. Browser
checks use externally installed Playwright via `PLAYWRIGHT_MODULE` and optional
`PLAYWRIGHT_BROWSERS_PATH`; no Node application dependency is required. Live browser
validation requires the separate `--execute-live` flag to avoid accidentally
spending on models/reviews. No automatic live test is
part of the default suite.

`uv run --locked python -m validation.run_ui_browser --prepare` verifies the
prepared path using the explicit offline fixture: ready before the first click,
no presentation run from preparing, and no repeated startup events in card runs.

### Verified implementation disposition

The historical first real UI campaign, **ui1**, passed all18 native cases and all10 lane
golden/effect expectations. Actual Chromium verified five explicit Run clicks,
sequential lanes, read-only navigation/reload, responsive/keyboard behavior and no
JavaScript errors. All16 task reviews agreed and all5 scoped harness reviews were
supported. [Versioned results, actual timings and source evidence](results/demo-ui1.md).
The UI was shut down gracefully and global hook/routes, old history, key/PVC and
ledger prefix were verified preserved. No additional inference was used to
regenerate the report. That versioned report describes the earlier allocated
implementation, not verification of today's repeatable mode. Old allocations and
costs remain historical records only: the current live UI never reads/enforces
them. [PR#67](https://github.com/caldeirav/sub15-breaker/pull/67) delivers the current
repeatable UI, startup preparation and progress/error fixes. Its owner-reported
acceptance is recorded below, separately from this historical campaign's results.

### Owner-reported acceptance — 2026-11-04

Repository owner **@caldeirav** reported: **“The UI demo has been tested thoroughly
for all use-cases”**, and explicitly requested documentation updates and merging
the branch into `main` through a PR. This records manual acceptance of the live
**D01–D05 UI scope**, not an agent-inferred sign-off or an automated test result.
Accepted implementation: `5e88991218cb0b21d6233bc965967f6216645c0b` on PR#67;
the acceptance/documentation follow-up does not change runtime code.

The delivered scope is repeatable paired execution without allocation/budget
gates, sequential lanes on the shared Qwen server, actual progress and golden/effect
panels, separate guard/component timers, post-run Gemini reviews, safe errors and
the optional `--prepare` startup workflow. D04/D05 remain controlled faults.

Automated evidence is separate: the implementation CI passed Python3.11–3.13;
the offline suite has743 tests, and both prepared and ordinary Chromium fixtures
passed six explicit runs including a repeat, sequential events, no navigation/reload
dispatch, desktop/mobile/keyboard checks and zero JavaScript errors. These fixture
checks are not relabelled as the owner's live tests. The owner statement does not
provide a new numerical latency/accuracy matrix; the versioned ui1 report and all
earlier failures, reviews, source records and historical costs remain unchanged.

This scoped UI acceptance does not resolve the rent false block (#55), broader
held-out evaluation (#56), full admission/load-tail metrology (#11), optional
acceleration (#13), soak (#39), artifact distribution/SBOM work (#10), or unrecorded
independent source-code/configuration reviews. #17 retains those distinct process
requirements; Gemini harness support is not an independent code-review sign-off.

## Inspect or replay without inference

```bash
uv run --locked python -m src.benchmark.demo --list-demo-cases
uv run --locked python -m src.benchmark.demo --phase nd13 \
  --protocol demo-qualification-v1 --demo-case pay-bill --guard llm --dry-run
```

These preview selectors/envelopes only; they do not check services/artifacts or
approve spending. The recorded campaign is **nd11 qualification /nd12 rehearsal**;
all its execution/review slots are spent. Use saved evidence for presentation
unless a distinct live allocation is approved.

On the evidence owner's machine, open
`.infra/benchmark-guard-harness/ready-golden-review-package/summary.html` or serve
the verified bundle:

```bash
uv run --locked python -m src.benchmark.review_backend \
  --serve .infra/benchmark-guard-harness/ready-golden-review-package --port 8090 \
  --token-file .infra/benchmark-guard-harness/ready-golden-read.token
```

This binds localhost only; it is **not a visualization application or live-run
endpoint**. The private read token is not a model/platform/store credential.
The retained package includes historical failures alongside the latest demo;
consolidating docs does not rewrite it. A fresh checkout does not contain that
local bundle. The versioned Markdown report is readable without it.

## Prepare a new live qualification and rehearsal

Read [prerequisites and artifact handoff](infra.md) first. This procedure is
conditional on **explicit operator approval**, not a one-command clean-checkout
release. Set `QUALIFICATION`/`REHEARSAL` to unused `ndN` values with `N >= 11`,
`CAMPAIGN` to a new capacity campaign ID, `ARTIFACT` to the verified export,
`BUDGET` to the existing cumulative ledger and `WORK` to a new private output
directory. Export these shell variables for the Python snippets below.

For service-only startup/checking of the installed stack, use
`bash scripts/demo_stack.sh start` / `status`; see the
[lifecycle guide](infra.md#service-only-start-stop-and-status). This starts no demo,
model probe, classifier priming or judge review. LM Studio/model must already be
loaded manually. Service readiness is not the frozen campaign/acceptance gate.

**Current limitation:** budget amendments in `demo_budget.py` for the latest
17+1 reviews are specifically bound to **nd11/nd12**, not reusable under new IDs.
A new run may need a reviewed additive namespace-specific allowance before
freezing. There is no generic approval/reset CLI. The freeze must reject
insufficient allowance; do not edit the ledger, reuse old IDs or create a new
budget to bypass it. The recorded global2048/512/$100 caps and historical holds
remain cumulative, not a new allowance.

Before allocation, verify there are no in-flight actions/Actors; inspect current
capacity and preserve history/key/PVC. Any previous exclusive reservation must
be explicitly released by the operator, retaining used counts. Do not delete
trials, prune events or replace the store. The demo reserves42 trials/192 actions/
1200 evidence slots: qualification14, rehearsal14 and14 presentation headroom.
Headroom is **not inference permission**.

### 1. Draft plans, reserve capacity and freeze together

With MLflow/configured stack available and before any model calls, create plans
using the implemented plan builder:

```bash
uv run --locked --env-file .env python - <<'PY'
import os
from pathlib import Path
from src.benchmark.demo import make_plan
from src.benchmark.deployment import private

work = Path(os.environ["WORK"])
work.mkdir(parents=True, exist_ok=False, mode=0o700)
common = dict(acting_model=os.environ["LM_STUDIO_MODEL"],
              capacity_campaign=os.environ["CAMPAIGN"])
q = make_plan(Path(os.environ["ARTIFACT"]),
              namespace=os.environ["QUALIFICATION"],
              protocol="demo-qualification-v1", **common)
r = make_plan(Path(os.environ["ARTIFACT"]),
              namespace=os.environ["REHEARSAL"],
              protocol="demo-rehearsal-v1",
              rehearsal_of=os.environ["QUALIFICATION"], **common)
private(work / "qualification.json", q)
private(work / "rehearsal.json", r)
PY

uv run --locked python -m src.benchmark.capacity \
  --reserve "$WORK/qualification.json" "$WORK/rehearsal.json" \
  --output "$WORK/capacity.json"
uv run --locked python -m src.benchmark.demo_qualification \
  --transport-probes "$WORK/transport"
uv run --locked python -m src.benchmark.demo_qualification --freeze-campaign \
  --qualification "$QUALIFICATION" --rehearsal "$REHEARSAL" \
  --capacity-campaign "$CAMPAIGN" --capacity-evidence "$WORK/capacity.json" \
  --transport-evidence "$WORK/transport" --artifact "$ARTIFACT" --budget "$BUDGET"
```

The non-effectful transport batch checks four catalog discoveries, effective30s
connect/430s response budgets and restoration, with no tool/model call. Freeze
binds both plans, code/image/artifact/calibration/fixtures/policy/model/profile,
transport/capacity evidence and exact per-case budgets. Use one frozen compatible
configuration throughout; changed code is not permission to repeat a spent case.
The campaign CLI defaults to the MPS plan; CPU requires an explicitly compatible
programmatic plan/freeze, not a silently mixed CLI setting.

### 2. Qualification: paired measurements, then native cases

```bash
uv run --locked python -m src.benchmark.demo --phase "$QUALIFICATION" \
  --protocol demo-qualification-v1 --capacity-campaign "$CAMPAIGN" \
  --artifact "$ARTIFACT" --budget "$BUDGET" --stage diagnostics --execute-demo
uv run --locked python -m src.benchmark.demo --phase "$QUALIFICATION" \
  --protocol demo-qualification-v1 --capacity-campaign "$CAMPAIGN" \
  --artifact "$ARTIFACT" --budget "$BUDGET" --execute-demo
```

Use printed output paths as `MEASUREMENT_DIRECTORY` and `NATIVE_DIRECTORY`. Each
process performs explicit [service startup](agent-flow.md#startup-versus-testing)
before testing. Qualification includes five unique golden action pairs,30 classifier
and15 LLM timing requests,14 native cases and17 allocated post-run reviews; maximum
88 local actor/guard requests includes four real startup probes. All priming and
cold costs stay unscored/separate. A failed paired/card gate stops, not retries.

The selectors `--stage cards --demo-case pay-bill --guard classifier` can execute
an allocated subset only after its controls/canaries exist. Selecting D04/D05 does
not create a new retry of an already spent fault record. A full acceptance report
requires the entire declared matrix.

### 3. Late readback, external review and report gate

Late state/restoration verification is an explicit helper, **not an automatic
side effect of opening a report**. After native cleanup, export `NATIVE_DIRECTORY`:

```bash
uv run --locked python - <<'PY'
import os
from src.banking_service.deploy import Deployment, DIRECTORY
from src.banking_service.http import RuntimeClient
from src.benchmark.demo_qualification import late_readback

d = Deployment()
d.refresh_credentials()
with d.forward("service/banking-store") as url:
    token = (DIRECTORY / "runtime.token").read_text().strip()
    late_readback(d, RuntimeClient(url, "Bearer " + token),
                  os.environ["NATIVE_DIRECTORY"])
PY

uv run --locked python -m src.benchmark.demo --phase "$QUALIFICATION" \
  --protocol demo-qualification-v1 --capacity-campaign "$CAMPAIGN" \
  --artifact "$ARTIFACT" --budget "$BUDGET" --review-demo "$NATIVE_DIRECTORY"
```

The last command **calls Gemini** once for the allocated16 task-criterion reviews
and one scoped harness review. Preserve errors/disagreements/negative support;
never re-query for a preferred verdict. Use its printed path as `REVIEW_DIRECTORY`.

There is no success-report CLI switch in `demo_qualification`: call the implemented
report function. Export `REPORT_PHASE=$QUALIFICATION`, all three output directories
and a new `NEW_REPORT_DIRECTORY`:

```bash
uv run --locked --env-file .env python - <<'PY'
import os
from pathlib import Path
import mlflow
from src.benchmark.demo_budget import DemoBudget
from src.benchmark.demo_qualification import report

mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001"))
b = DemoBudget(Path(os.environ["BUDGET"]))
measurement = os.environ.get("MEASUREMENT_DIRECTORY")
result = report(b, b.phase(os.environ["REPORT_PHASE"]),
                Path(os.environ["NATIVE_DIRECTORY"]),
                Path(measurement) if measurement else None,
                Path(os.environ["NEW_REPORT_DIRECTORY"]),
                reviews=Path(os.environ["REVIEW_DIRECTORY"]))
print("qualified:", result["qualified"])
PY
```

This audits saved traces/allocations/source hashes/startup/golden/readiness/physical
counters/reviews/late state and writes JSON/HTML/Markdown, with no inference or
banking-tool dispatch. Only its successful source-bound marker unlocks rehearsal.

### 4. Fresh rehearsal and presentation boundary

```bash
uv run --locked python -m src.benchmark.demo --phase "$REHEARSAL" \
  --protocol demo-rehearsal-v1 --rehearsal-of "$QUALIFICATION" \
  --capacity-campaign "$CAMPAIGN" --artifact "$ARTIFACT" --budget "$BUDGET" \
  --execute-demo
```

Record the new native directory; perform the same late-readback helper, then
`--review-demo` with the **same rehearsal flags** for its one allocated wiring
review. Generate the report with `REPORT_PHASE=$REHEARSAL`, the rehearsal directories,
a new report destination and `MEASUREMENT_DIRECTORY` unset (no duplicate paired
accuracy is invented). Maximum66 local/1 external includes two startup probes.
Rehearsal uses14 fresh native cases on the unchanged configuration.

Qualification/rehearsal success is not owner acceptance or allocation for another
live presentation. Record actual human review in #17. Saved replay costs no model
requests; live presentation needs separately approved fresh IDs/budgets/readiness.
Never repeat a failed case or delete its start marker.

## Read-only backend contract

`review_backend.py` consumes an allowlisted array of `{id, directory, report}`
entries (optional supplemental `evidence` paths) and writes a **new** sanitized
bundle. Source/payload hashes must verify; it does not serve arbitrary files.

```bash
uv run --locked python -m src.benchmark.review_backend \
  --sources APPROVED_SOURCES.json --output NEW_REVIEW_BUNDLE
uv run --locked python -m src.benchmark.review_backend \
  --serve NEW_REVIEW_BUNDLE --port 8090 --token-file PRIVATE_READ_TOKEN_FILE
```

Schema **`demo-review-v1`**, mode=`saved_replay`, `live_dispatch_supported=false`,
`inference_on_read=false`. At most16 request connections, bounded socket reads,
localhost Host plus bearer read-token authentication, private0600 token file,
no permissive CORS or raw provider/platform credentials. All responses are JSON,
`Cache-Control: no-store`. This is not a public Internet service.

| GET endpoint | Meaning |
| --- | --- |
| `/api/v1/readiness` |Bundle verification; live store explicitly `not_probed` |
| `/api/v1/accounting` |Recorded ledger totals/holds/prefix hash, not an invoice or allocation |
| `/api/v1/cases` |D01–D05 manifest and producer/expected outcomes |
| `/api/v1/runs` |Saved-run completeness/readiness and limitations |
| `/api/v1/runs/{id}` |Metadata and normalized results |
| `/api/v1/runs/{id}/results` |Cases, decisions, receipts/state differences, coverage, accuracy, startup/performance and trace links |
| `/api/v1/runs/{id}/events?after=0&limit=100` |Logical ordered replay, max200/page, `sequence` and nullable `next_after` |

Write methods405; bad host/token401; unknown paths/IDs404; bad pagination400.
No endpoint accepts a command, filesystem path, ticket, prompt or live execution.
Missing/unstarted/setup-failed cases remain visible. Unrecorded values are null,
not fabricated zeros. Event timestamps are null with `time_basis=logical_order_not_wall_clock`;
use MLflow spans for real timing, not a fabricated replay clock.

`golden_accuracy` shows expected and both observed verdicts/correctness plus exact
denominators; `service_startup` shows readiness/load/priming/model probes unscored.
Core/whole-review/claim timers have distinct ns fields. Readiness retries are their
own observations, never model/action retries. Capacity is a recorded snapshot,
not current health. Public state changes expose numeric/boolean differences;
other values are redacted digests. Source manifests stay operator-private.

Opening, paging or replaying this saved backend issues **zero model/tool/judge
calls**. The live UI above is a different authenticated execution surface; it does
not turn this replay adapter into a runner or mix historical snapshots with new
execution. Current delivery/acceptance is tracked in #60/#17.
