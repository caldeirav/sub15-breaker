# Five-card live demo UI and operator runbook

[Local setup](infra.md) · [Agent flow](agent-flow.md)
· [Validation](validation.md) · [Latest versioned results](results/demo-nd11-nd12.md)

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
gates. The live UI allocates ten fresh lanes (two per card, including independent
fault controls): **18 native cases** in a one-run-per-card campaign. The older CLI
qualification/rehearsal protocol below has14 cases because it reuses the shared
error/cancel control records for D04/D05. Neither count is a model-accuracy
denominator. D01–D03 real guards review every prefix action. Rent remains outside
these cards but in the full test and known quality limitation #55.

## Live web interface — end to end

The primary UI is **live execution, not saved replay**. Choose a card on the left
and click **Run both routes**. The classifier and LLM lanes appear side by side,
but run **sequentially** because both acting agents and the LLM reviewer share one
Qwen server. The immutable allocation declares/displays the arm order and alternates
which arm runs first across cards. Only one pair may run at a time.

### Prerequisites and first-time setup

1. Clone the repository/feature branch, install Git, uv and Python3.11–3.13, then
   `uv python install` and `uv sync --locked`. No Node/npm build is needed for the
   application; FastAPI/uvicorn serve local HTML/CSS/JavaScript with no CDN assets.
2. Follow the [complete local infrastructure guide](infra.md): a reviewed rootful
   Podman VM, owned Kind/Cilium/Substrate/gVisor installation, enforcement Gateway,
   digest-bound banking store/Actor image, `native-measure-v2` profile and explicit
   retained-trial limits. A manifest or controller install alone is not readiness.
3. Obtain the **compatible frozen classifier export and cumulative v4 ledger**
   from the operator, under `.infra/benchmark-guard-harness/`. Weights/credentials
   and the ledger are not published or generated automatically from a checkout.
   The real UI cannot run without that handoff; base/random weights and a new empty
   ledger are not substitutes. For a genuinely new release/profile, initialization
   and artifact distribution still require explicit operator provenance (#10).
4. Create `.env` from `.env.example` only if absent. Set the exact approved
   `LM_STUDIO_MODEL=qwen/qwen3-30b-a3b-2507`, local provider port1234, HTTP MLflow
   port5001, and the authorized Gemini2.5Flash credentials/profile. This live UI
   includes paid external review and sends projected synthetic evidence externally.
   Never connect real banks, real payment credentials or a shell executor.
5. Manually start LM Studio and load the approved cached model with context8192.
   Start MLflow once with the [documented backend/artifact paths](../README.md#run-locally)
   if this installation has no tracking database yet. On the existing installation:

```bash
bash scripts/demo_stack.sh start
bash scripts/demo_stack.sh status --json
```

The service manager resumes only owned installed services, checks the model without
generation and renews scoped driver credentials. It does not start a live case,
prime the classifier or run Gemini. It will not download/build a missing stack or
replace old data. Use the setup guide, not `destroy`, to resolve prerequisites.

### Allocate a fresh UI campaign before serving

The browser cannot choose budgets, model/artifact paths, infrastructure endpoints
or arbitrary commands. Each click consumes one **preallocated pair of fresh IDs**;
failed/interrupted runs and duplicate clicks cannot reset them. Choose an approved
unused namespace `uiN` and freeze the current source/model/image/data bindings:

```bash
# Read-only proposal: builds fixture inputs but makes no model requests.
uv run --locked --env-file .env python -m src.demo_ui.allocation --campaign uiN

# Only after actual operator approval; retain the existing cumulative budget.
uv run --locked --env-file .env python -m src.demo_ui.allocation --campaign uiN \
  --freeze --owner-reason "DESCRIPTION OF THE ACTUAL APPROVED CAMPAIGN"

# Authenticate/read capacity and reserve this campaign without pruning history.
uv run --locked --env-file .env python -m src.demo_ui.allocation --campaign uiN \
  --reserve-capacity
```

Replace `uiN` with a real numeric namespace. If another capacity campaign is active,
inspect it first. Once no Actors, native listeners or unresolved actions remain,
explicitly add `--release-prior-campaign EXACT_PRIOR_ID` to the capacity command.
This retains the prior reservation's used counts and the same state/key/PVC.
Never edit/reset the database, ledger, spent markers or allowance files.

The default one-run-per-card allocation has maxima **63 local actor/guard requests,
21 Gemini operations**, **10 classifier priming forwards** and **18 fresh trials**.
This includes six native controls, two identical-prefix real canaries and two
startup model probes. Each D01/D03 click reserves up to28 local/9 external calls;
D02 up to3 local/1 external; D04/D05 zero real case-model calls/1 external each.
Startup/canaries are a separately declared once-per-session allocation. Globals
2048 local/512 external/$100 and all historical holds remain cumulative. A larger
`--repetitions` needs explicit new approval and still fails if the global envelope
cannot cover its worst-case holds; it is not permission to resample for green.

### Start the UI and run a selected card

```bash
uv run --locked --env-file .env python -m src.demo_ui --campaign uiN
```

Open **`http://127.0.0.1:8091`**. Read the separate local **UI run capability** from
`.infra/live-demo-ui/ui.token` and enter it in the unlock form. This is not the
saved-replay token and never a provider/platform credential. It is private0600,
held server-side after sign-in through an HttpOnly/SameSite=Strict session cookie;
Run POSTs additionally require same-origin and a per-session CSRF value.

Opening, signing in, selecting cards, reconnecting or paging events never starts
inference. An explicit Run click claims both lane slots before any work. On the
first click, the backend verifies actual gVisor/Actor identity, performs the
allocated functional model probes and two fixed unlabelled classifier priming
passes, then runs the predeclared native controls/canaries. It keeps the classifier
resident on the measured worker and installs one native hook/bridge for the UI
session. The same compiled agent/native store path is reused, not a second loop.

One arm runs, is fenced/cleaned up/reconciled, then the other runs on equivalent
fresh state. Scoped driver authority is renewed before each arm so an idle pause
does not blindly reuse expired credentials; renewal never runs a model or replays
an action. There is no concurrent acting-model/reviewer load from the two lanes,
backend substitution, response repair, preferred-outcome retry or shared-model
reload. A browser disconnect does not cancel or rerun a payment; reconnect reads
the existing active job. Restarting an already started campaign does not reissue
startup/case calls: interrupted/spent sessions fail closed and need a fresh approved
allocation, not deletion of their markers.

### Interpret the display

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
- **Gemini:** after both arms, four task-criterion reviews per genuine episode and
  one scoped pair/harness review. D02/D04/D05 use the scoped harness review only.
  Review time/cost is outside guard performance. Errors, disagreement and negative
  verdicts stay visible and never overwrite CODE or human acceptance.

Both arms can be displayed together without being statistically identical: agents
may propose different calls, and shared-device idle/cache conditions still vary.
These are curated live observations, not a held-out safety or p99/SLO claim.

### Shutdown, evidence and API boundary

First Ctrl-C the UI and allow the active pair/review to finish and owned native
hook/routes to restore. Do not force-kill during a mutation. Then use
`bash scripts/demo_stack.sh stop` if needed; it refuses active native work and
leaves borrowed services, LM Studio/model, shared VM and data untouched.

Private UI evidence lives in `.infra/live-demo-ui/uiN/`: per-job `public.json`,
append-only `events.jsonl`, source-record hashes and raw review records. Runtime
records/startup/controls are in its `runtime/` directory and linked MLflow runs.
All failed/partial attempts remain. Public events omit credentials, complete bank
state, raw prompts and ticket capabilities; tool arguments shown in final panels
are bounded canonical/redacted synthetic values rendered as text, never HTML.

The new loopback API under `/api/live/` has authenticated status, explicit Run POST,
run results and resumable SSE observations. It never accepts paths/prompts/commands
or browser infrastructure credentials. A single worker and operator lock serialize
the global hook/bridge and both arms. There is no arbitrary live cancel endpoint;
D05 is the declared cancellation scenario. API reads cannot issue inference. The
older [saved-review API](#read-only-backend-contract) stays separate and read-only.

### UI validation without spend

Default `bash scripts/test.sh` includes fixture-backed API, auth/CSRF/Host/body,
idempotency, sequential scheduling, events, failure and allocation tests. The
explicit `validation.live_ui_fixture_server` and `validation.run_ui_browser` are
**offline UI test fixtures**, never the real demo or a fallback runtime. Browser
checks use externally installed Playwright via `PLAYWRIGHT_MODULE` and optional
`PLAYWRIGHT_BROWSERS_PATH`; no Node application dependency is required. Live browser
validation requires the separate `--execute-authorized-live-campaign` flag, an
explicit campaign and its frozen one-shot allowance. No automatic live test is
part of the default suite.

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
