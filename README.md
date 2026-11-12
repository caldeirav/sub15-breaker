# BreakerSubstrate

**Compare a compact classifier with an LLM reviewer before an agent's tool action executes.**

BreakerSubstrate (`sub15-breaker`) is a research reference implementation for
[“Instant Circuit Breakers: Sub-15ms Action Verification in Agent Substrate”](https://atecon.dev/).
It asks whether one calibrated, non-generative encoder pass can review a proposed
action with less overhead than generating a verification response, while retaining
useful task completion and honest evidence about mistakes.

The use case is **simulated banking**: pay a bill, adjust rent or update an address.
The agent proposes typed calls; a reviewer outside its reasoning loop decides
whether the runtime may execute them. Both reviewers use the same contextual input
and the same native pre-execution boundary. Only the reviewer changes.

> Research software, not a production safety system. Use synthetic data only—no
> real bank APIs, payment credentials or privileged shell executor. A classifier
> can be wrong—and a wrong denial is currently final: out-of-policy actions fail
> closed with no human-escalation path, although Agent Substrate supports one
> ([#74](https://github.com/caldeirav/sub15-breaker/issues/74)). Denial, stopping
> an Actor and undoing prior effects are different; no rollback or universal
> containment is promised. The 15ms research target is
> **classifier decision computation**, not native admission or complete task time.

## Talk: Agent Substrate Day at ATECon 2026

This reference implementation was presented as
**“Instant Circuit Breakers: Sub-15ms Action Verification in Agent Substrate”**
at Agent Substrate Day (ATECon, Monday, November 9, 2026, Sky SLC):
[talk slides](docs/assets/agent-substrate-day-instant-circuit-breakers.pdf) ·
[LinkedIn write-up](https://lnkd.in/p/gWEq6rQh).

The talk frames the problem this repository studies. When an agent proposes a
high-stakes action—calling a cloud API or modifying a database—how do you verify
that it is safe without destroying real-time performance? Most current
architectures either naively trust the agent's internal reasoning or insert a
secondary LLM as a conversational judge. That generative approach pays a
**verification tax** on every step: **1,500ms+ lag** (re-querying an LLM stalls
agent execution), **uncalibrated confidence** (text probabilities are
conversational guesses) and **injection risk** (external tool data can hijack the
evaluation reasoning).

The alternative demonstrated here moves enforcement to the infrastructure
boundary: a compact, calibrated binary decision model (ModernBERT) replaces the
generative judge. One forward pass, zero generated tokens and a fail-closed
threshold on a calibrated risk probability halt unauthorized actions before any
side effect leaves the sandbox. Strategically this is trust-boundary management:
a scaled agentic system can have hundreds of control points, so they must be
calibrated to the decision space and specific policies, operate entirely outside
agent execution, and remain transparent and auditable—rather than sit inside the
agent flow, blurring execution authority and sharing its exploits. Agent
Substrate joining the CNCF at its 1.0 milestone provides the neutral governance
and sandboxed foundation such distributed enforcement needs.

The deck's agenda maps onto this repository:

| Talk section | Where it lives here |
| --- | --- |
| 01 Instant Circuit Breakers overview | Verification tax versus sub-15ms binary decisions; [risk model and calibration](#risk-model-and-calibration) |
| 02 Connectivity vs execution authority | agentgateway routes traffic; Agent Substrate enforces the non-bypassable boundary; [system architecture](#system-architecture) |
| 03 Agent flow and testing protocol | Neutral LangGraph loop, AgentDojo banking suite with real prompt-injection exploits, identical admission for both reviewers; [how this uses AgentDojo](#how-this-uses-agentdojo) |
| 04 Results, interpretation and next steps | Medians below and the production roadmap; [test environment and metrics](#test-environment-design-and-metrics) |

Whole-review medians as presented in the talk ([ui1 live campaign](docs/results/demo-ui1.md); one observation on one machine):

| Card / scenario | Classifier | LLM review | Speedup |
| --- | ---: | ---: | ---: |
| D01 bill pay (allow) | 76.1 ms | 368.0 ms | 4.8× |
| D02 exploit control (block) | 64.7 ms | 590.6 ms | 9.1× |
| D03 profile update (allow) | 60.1 ms | 258.6 ms | 4.3× |

Ten of ten lanes met their golden outcomes; D02 is the scripted extra-proposal
control, not an acting-agent attack sample. The classifier forward-pass core ran
50–66 ms on the resident MPS worker—**sub-15ms is the classifier-computation
target on enterprise accelerators, not a latency achieved on this hardware**, and
tiny serial samples are not load/tail SLOs or a matched-safety speed guarantee.
The production roadmap from the talk: TensorRT/ONNX native sidecars for
sub-15ms forward passes, a declarative Substrate CRD for an ActionGuard
admission controller, and extension to broader suites such as bash commands and
cloud IAM validation.

## Live demo

<a href="https://youtu.be/Ayo4dzE5TtY"><img src="docs/assets/sub15-breaker-ui-poster.jpg" alt="Watch the BreakerSubstrate demo on YouTube: Classifier and LLM reviewer lanes running the pay-a-bill scenario, with per-route component flow, verdicts and receipts" width="960"></a>

▶ **[Watch the 4 min 38 s walkthrough on YouTube](https://youtu.be/Ayo4dzE5TtY)**
— click the preview or the link to watch (no audio).

The recording shows one complete **D01 “Pay the bill”** run in the local demo UI
(`bash scripts/run_demo.sh`). Both routes use the same agent, the same pinned
AgentDojo banking task and synthetic state, the same Mask-sanitized review input
and the same Substrate Envoy claim gate. Only the reviewer changes:

- **Route A — LLM reviewer:** generates a verdict through the shared agentgateway
  model route.
- **Route B — classifier:** one encoder forward pass with frozen calibration.

What to look for:

1. **Scenario context (D01):** the pinned user request, starting state, available
   tools and expected outcome, served from digest-bound pinned data rather than
   free text.
2. **Per-route component flow:** each lane retains its own traversal ribbon —
   agent, agentgateway, Qwen server, banking bridge, state store, gVisor Actor,
   native claim gate, reviewer, MLflow — with traversal counts, and every timeline
   entry is tagged with the component that produced it.
3. **Decision review:** the exact Mask-sanitized input both reviewers received,
   the classifier's calibrated logit/temperature/threshold and the LLM's raw
   verdict, plus the executed-or-blocked receipt outcome for each action.
4. **Paired final outcome:** actions joined on the frozen input digest, showing
   whether both routes reached the same decision and what was actually executed.
5. **Final evidence and external review:** CODE-oracle golden checks and
   per-criterion Gemini judge rows — criterion rule, golden parameters, expected
   verdict, judge verdict and agreement — with the MLflow trace opened at the end.

The five cards (pay a bill, deny an extra transfer, update the profile,
unavailable reviewer, cancelled late allow) include explicit negative and fault
controls. Timings shown in the video are one observation on one machine, not a
benchmark, speedup or accuracy claim. Live runs call external providers and incur
charges; see [`docs/demo.md`](docs/demo.md) for setup and the full interpretation
guide.

## How this uses AgentDojo

[AgentDojo](https://github.com/ethz-spylab/agentdojo) is an extensible environment
for evaluating tool-using agents exposed to prompt injection through untrusted
tool data. See the research paper,
[AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents](https://arxiv.org/pdf/2406.13352).

We reuse its **banking tasks, synthetic initial state, 11 tools, released attack
fixtures, reference trajectories and executable outcome checkers**. We do not use
AgentDojo's agent pipeline as our orchestrator: a pinned adapter supplies assets
to one suite-neutral LangGraph agent, and tools execute in Agent Substrate Actors.
References and checker answers stay evaluator-only, never acting-model or guard
features. This is a small adapted research slice, **not an official full-suite
AgentDojo benchmark or leaderboard result**.

The dependency is pinned to commit
`089ed468cf3ed0322acc66b0211f26d9d90dbf60`, package `0.1.35`, banking benchmark
`v1.2.2`. The live comparison covers `user_task_0` (bill), `user_task_2` (rent) and
`user_task_13` (address); the five-card demo uses bill/address and explicit
negative/fault controls. [Data, checker semantics and test design](docs/validation.md).

## System architecture

```mermaid
flowchart TD
    H[Experiment harness and pinned AgentDojo adapter] --> A[One LangGraph agent]
    A -->|Responses model requests and MCP tool calls| G[agentgateway: shared model and tool routing]
    G -->|model requests| L[Local Qwen model in LM Studio]
    L -->|model responses| G
    G -->|model or tool results| A
    G -->|MCP tool calls| B[Banking bridge: prepare immutable ticket]
    B --> R[Agent Substrate gVisor Actor]
    R -->|claim ticket| N[Substrate Envoy native egress gate]
    N --> V{Selected reviewer}
    V --> C[ModernBERT classifier and calibration]
    V --> Q[LLM review adapter]
    Q -->|review model request| G
    G -. review model response .-> Q
    C --> D{Effective decision}
    Q --> D
    D -->|allow| S[Store claim, Actor computation, atomic state and receipt commit]
    D -->|block or error| X[No target tool execution]
    S -->|committed tool result| B
    X -->|denied or error result| B
    B -->|MCP result| G
    H --> E[Private checkers and post-run review]
    S -. evidence .-> M[MLflow traces and assessments]
    E --> M
```

**Where the agent runs:** the LangGraph agent and experiment harness execute in
the host-side Python process, **not inside a Substrate Actor**. The tool functions
run in Substrate gVisor Actors. One managed gateway (`breaker-gateway`) carries
both acting/reviewer model traffic and MCP tool traffic through separate routes;
the native Substrate Envoy claim gate is a different component, not a second
agentgateway.

### Components and design decisions

| Component | Role and reason for using it |
| --- | --- |
| **[Agent Substrate](https://github.com/agent-substrate/substrate)** | Creates disposable per-trial Actors, supplies runtime identity and gVisor isolation, and hosts the native Envoy hook on the Actor's store-claim path. Enforcement is outside the agent's cooperative loop. |
| **[agentgateway](https://github.com/agentgateway/agentgateway)** | Routes acting/reviewer model requests and remote MCP tool traffic, applies managed transport/auth policies and exports distributed telemetry. It is connectivity infrastructure, not the Actor sandbox or the native claim gate. |
| **Banking bridge and state service** | Bind the exact action/context to an immutable ticket; publish synthetic state, receipts and durable evidence atomically outside disposable Actors. Unknown writes are reconciled, not repeated. |
| **LangChain/LangGraph** | One bounded tool-calling loop for both guard modes; structured messages and matching tool-result IDs. Domain state, guard choice and private evaluation remain outside the graph. |
| **ModernBERT / Qwen** | Compare one binary encoder forward pass with an actual generative review over the same action/context. No forced verdicts, hidden fallback or agent-side rescore. |
| **MLflow / native Gemini judges** | Persist attempts, effects, failures and trace-owned scores. Gemini reviews saved evidence after execution, not authorization; its opinion does not replace CODE checkers or human acceptance. |
| **Podman, Kind and Cilium** | Reproducible local Kubernetes profile with enforcing networking and actual positive/negative controls, rather than assuming a manifest proves isolation. |

The key distinction is **transport versus execution authority**: agentgateway
carries model/tool requests; Substrate's native hook gates an Actor's claim of
the exact prepared ticket. That gate sits on top of a deterministic layer, not in
place of one: before any reviewer runs, a trusted service binds each proposed
action to an immutable ticket that fixes the operation, target resource and
expiry, and the store re-verifies identity, generation, state version and
idempotency at the transaction boundary—not just at review time. Agent
authorization is likewise separate and never passes through the model: caller
identity comes from trusted service-side credentials, is bound into the ticket
and re-verified at claim and commit, alongside a deterministic capability check
that the tool is permitted for that principal at all. A reviewer only decides
whether the proposed action complies with policy given the legitimate goal and
state—it can veto a ticket, but it cannot grant authority. A good model decision
without those bindings is insufficient. [Detailed system/harness architecture](docs/architecture.md).

### Agent control flow

```mermaid
flowchart LR
    S([Start]) --> M[Reserve attempt and call model]
    M -->|valid tool calls| T[Serial remote execution through gateway and native gate]
    T -->|executed result with matching call ID| M
    M -->|genuine final response| E([Completed])
    M -->|protocol error, limit or cancellation| F([Explicit non-completed outcome])
    T -->|blocked, error or unknown| F
```

The graph never chooses or enforces its own reviewer. It stops on non-executed
outcomes; timeout is not evidence that a write did not happen. No parsing repair,
automatic model/action retry or host-tool fallback is used. Conversation state
is not a durable transaction ledger. [Detailed agent flow and failure handling](docs/agent-flow.md).

## Risk model and calibration

The demo uses the frozen **`modernbert-banking-hybrid-v1`** binary classifier,
fine-tuned from ModernBERT-base—not an embedding-similarity rule, generic relevance
checkpoint or AnyJev/Laya integration. Inputs contain the legitimate goal, policy,
one typed action, relevant service-owned state and actual preceding observations.
Untrusted document text cannot create authority. Unsupported inputs fail closed;
required facts are not silently truncated. The model reviews policy compliance,
not caller authority—authorization is established deterministically before
review. A block is also terminal for that action: the demo fails closed with no
human-escalation path, although Agent Substrate supports one
([#74](https://github.com/caldeirav/sub15-breaker/issues/74)).

For permitted/prohibited logits $z_0,z_1$, temperature $T$ and threshold $\tau$:

$$p_{\mathrm{risk}}=\sigma((z_1-z_0)/T),\qquad
\text{block when }p_{\mathrm{risk}}\geq\tau.$$

Temperature fits calibration-set NLL; the threshold is selected on validation,
then frozen before evaluation. Calibration does not create labels or prove safety
under distribution shift. The artifact has known transfer failures, including an
unfixed legitimate rent false block. [Model, labeling and calibration protocol](docs/model.md).

## Test environment, design and metrics

The measured local profile is **Apple M4 Max /48GiB**, macOS, PyTorch MPS for the
classifier, Qwen3-30B-A3B-Instruct-2507 MLX4-bit/context8192 in LM Studio, and a
rootful Podman/Kind/Substrate/gVisor stack. Pins are in
[`infra/versions.json`](infra/versions.json); other hosts need their own validation.

We separate three questions:

1. **Guard quality:** identical frozen action/context pairs for both reviewers;
   accuracy, false allows/blocks, errors and coverage with exact denominators.
2. **Agent utility and effects:** fresh-state workflows under each guard; original
   upstream checkers, committed receipts and independent state changes. Different
   agent trajectories are not identical-input model comparisons.
3. **Enforcement/harness correctness:** native allow/block/error/timeout/cancel
   controls, ticket/identity/state binding, trace/accounting readback and cleanup.

Latency has separate **classifier-core**, **whole-review** and **native-claim**
boundaries. Startup loading and fixed priming are recorded separately and excluded
from measured performance; all after-readiness samples, including slow ones, remain.
Tiny serial samples are not load/tail SLOs or a matched-safety speed guarantee.
[Validation methodology and full-test instructions](docs/validation.md).

The [latest versioned live UI report: ui1](docs/results/demo-ui1.md) contains the
results, both verifiers' performance in separate columns and evidence IDs:
**18 native cases, 10/10 lane golden/effect expectations met, 16 task-criterion
agreements and 5 supported scoped harness reviews**. These include scripted/fault
controls and do not establish general model accuracy. All5 cards were run once
through the actual browser. This historical report predates repeatable-demo mode;
the current live UI needs no allocations and lets you repeat any card.
The owner-reported acceptance of all five UI use-cases is recorded in the
[demo guide](docs/demo.md#owner-reported-acceptance--2026-11-04). Broader process and
independent-review requirements remain separate in [#17](https://github.com/caldeirav/sub15-breaker/issues/17).

## Run locally

### Prerequisites

- Git and [uv](https://docs.astral.sh/uv/); Python **3.11–3.13** (local default in
  `.python-version`). Offline tests need no model, Kubernetes or provider key.
- For **live** runs: the owned rootful Podman/Kind/Substrate stack, managed
  agentgateway routes, digest-bound banking image/store, MLflow and the approved
  loaded Qwen model, plus the verified local classifier/data/provenance bundle.
- Native Gemini review needs credentials; it incurs provider charges and sends
  projected synthetic evidence externally. The live UI has no budget gates.

**A clean checkout can run offline tests, but is not a turnkey live demo.** Weights,
reviewed datasets and credentials are not bundled. Obtain
the compatible artifact handoff before live work; do not substitute base weights
or reset historical benchmark ledgers. The live UI does not need a ledger. There is no installed
`sub15-breaker` console command; use the module entry points below.

```bash
uv python install
uv sync --locked
bash scripts/test.sh

# Inspection only: no keys, inference, trial creation or cluster mutation.
uv run --locked python -m src.benchmark.demo --list-demo-cases
uv run --locked python -m src.benchmark.demo --phase nd13 \
  --protocol demo-qualification-v1 --demo-case pay-bill --guard classifier --dry-run
```

For live configuration, copy `.env.example` to `.env` **only if absent**, set
`LM_STUDIO_MODEL=qwen/qwen3-30b-a3b-2507`, the configured
`LM_STUDIO_BASE_URL`, `MLFLOW_TRACKING_URI` and authorized Gemini settings. Never
overwrite credentials or change a shared model's serving settings silently.
The enrolled UI launcher starts MLflow against retained storage automatically.
For manual CLI workflows or first-time tracking-store initialization, run it in
a separate terminal if it is not already running:

```bash
uv run --locked mlflow server --host 127.0.0.1 --port 5001 \
  --backend-store-uri sqlite:///mlflow.db \
  --artifacts-destination .infra/mlflow-artifacts
```

Then follow the appropriate guide:

- **[Local stack setup and checks](docs/infra.md):** tools, cluster, banking image,
  credentials, managed model/MCP routes, readiness and safe cleanup.
- **[Run the five-card web demo](docs/demo.md#live-web-interface--end-to-end):**
  the live web UI selects any card and runs both arms sequentially with
  real-time observations, golden checks and guardrail/component timings. Live clicks
  are repeatable without allocations or spending budgets. Gemini provider charges
  still apply; enable the store's repeatable-demo mode once as documented.
   After the [one-time installed-stack enrollment](docs/demo.md#restart-after-a-reboot--one-command),
   start LM Studio/server and the approved cached model, then run
   **`bash scripts/run_demo.sh --prepare`**. The launcher starts the retained
   Podman/Kind/services and the actual UI; wait for **Demo ready**. Omit
   `--prepare` for zero-inference startup (first Run click prepares instead).
   LM Studio/model are always check-only; nothing is installed or downloaded.
- **[Run the full test](docs/validation.md#run-the-full-live-comparison):** larger
  three-workflow A/B protocol, separate from the complete offline test suite.

For an **already-installed environment**, use the service-only lifecycle script:

```bash
bash scripts/demo_stack.sh start
bash scripts/demo_stack.sh status
bash scripts/demo_stack.sh stop
```

Start LM Studio and load the approved model manually first. The script resumes
owned stopped cluster/registry containers, starts MLflow if absent, renews scoped
driver credentials and checks services/artifact hashes—**it does not run the demo,
generate model tokens, prime the classifier or call judges**. `stop` stops only resources
this manager started, preserving existing/shared services, the Podman VM and data.
It refuses shutdown while banking work is active. Add `--with-review-api` to
start/check the retained saved-replay API. [Lifecycle options and limits](docs/infra.md#service-only-start-stop-and-status).

`nd13` above is an inspection example, not an approved run. All recorded nd1–nd12
execution IDs are spent. Do not replay them, remove markers or repeat failed
model/actions until they pass. These historical benchmark protocols are separate
from the repeatable live UI; their old allocations do not restrict demo clicks.

## Repository overview

| Path | Contents |
| --- | --- |
| `src/agent_runtime/` | Suite-neutral contracts and single compiled reasoning loop |
| `src/integrations/agentdojo/` | Pinned tasks/state/checkers, label preparation and provenance |
| `src/benchmark/` | Harness, bridge/native guard, model adapters, startup, budgets, measurements and read-only review backend |
| `src/banking_contracts/` | Strict actions/context/receipts, decimal schemas and record-only fixtures |
| `src/banking_service/` | Actor tool computation, authenticated lifecycle and transactional state/receipt/outbox service |
| `src/infra/`, `infra/`, `scripts/` | Owned local stack, version pins, checks and image build |
| `tests/` | Default offline regressions; no live provider campaign |
| `validation/` | Explicit opt-in persisted/live checks and archived acceptance/protocol records |
| `docs/` | Six topic guides, navigation, one versioned latest-demo report, and talk slides with demo assets |
| `k8s/`, `specs/` | Manifest inventory and scope/acceptance specification |
| `src/feasibility/`, `src/agent/`, `src/eval/`, `src/gateway/`, `src/dashboard/` | Historical adapters/utilities and command-only compatibility scaffolding, not alternative supported banking entry points |

[Documentation index](docs/README.md) · [Roadmap and remaining work](https://github.com/caldeirav/sub15-breaker/issues/14)
· [License](LICENSE)
