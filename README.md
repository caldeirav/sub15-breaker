# BreakerSubstrate

**Pre-execution action verification for agentic runtimes, without generating verification tokens on the classifier path.**

BreakerSubstrate (`sub15-breaker`) is the research reference architecture for the AgentSubstrate Day NA 2026 session [“Instant Circuit Breakers: Sub-15ms Action Verification in Agent Substrate”](https://atecon.dev/). It investigates a practical question: **can a compact, calibrated classifier reject a dangerous tool action before execution, with less overhead than asking a generative model to review it?**

The reference use case is a **simulated banking agent**. A user asks it to pay a bill, adjust a scheduled payment or update an address. The model proposes typed tool calls; untrusted invoices or tool responses may try to redirect those calls. We reuse AgentDojo's synthetic tasks, tools, state and executable checkers rather than build a new financial benchmark or expose a general-purpose shell.

The comparison is between **A: generative verification** and **B: one compact neural encoder inference over the same action and trusted context**. Both belong at the same native Substrate pre-execution boundary, outside the agent's reasoning loop. The sub-15ms objective is a research hypothesis—not a measured result, safety guarantee or hardware-independent SLA.

> **Research software, not a production safety boundary.** Use synthetic data only; do not connect real bank APIs, money, payment credentials or a privileged executor. A denied request is not acknowledged Actor termination, and neither denial nor termination rolls back prior effects.

For delivery status, dependencies, implementation blocks and acceptance, use the [GitHub roadmap](https://github.com/caldeirav/sub15-breaker/issues/14) and [implementation issues](https://github.com/caldeirav/sub15-breaker/issues). This README describes the project, architecture and technical decisions, not a release ledger.

## Why this design?

1. **Verify before mutation.** Reviewing a trace after an unauthorized transfer is too late to prevent that transfer. Enforcement must inspect the proposed action before the tool consumes it.
2. **Separate proposal from authority.** The acting model, its explanations and tool-returned text are untrusted. Identity, policy, intent provenance and state versions must come from services outside the agent—not from its assertion that an action is safe.
3. **Separate reasoning from classification.** A generative reviewer produces tokens; a compact encoder can make a binary classification in one forward pass. Lower and more predictable overhead is a hypothesis to test at comparable quality, not an assumed advantage.
4. **Use calibrated estimates, not verbal confidence.** A score between zero and one is not automatically a meaningful probability. Independent labels, held-out calibration, error rates and coverage are necessary.
5. **Retain benchmark controls and isolation.** A model can miss an unsafe action. Reuse the working platform, schema/state checks, limits and sandbox; do not build production IAM, elaborate security policy or HA for this benchmark.
6. **Measure rather than manufacture the comparison.** Do not add artificial delays to A, assume millisecond performance for B, hide failures or count a denied-everything agent as a successful system.

## Agent design and control flow

The benchmark uses **one compiled LangGraph** in [`src/agent_runtime/runner.py`](src/agent_runtime/runner.py), with LangChain messages/model integration and injected remote execution. The suite-neutral runtime has no AgentDojo dependency. The [pinned banking adapter](src/integrations/agentdojo/banking.py) supplies tasks and private checkers; it does not inherit AgentDojo's agent pipeline or execute live tools on the host.

### Compiled reasoning loop

The graph has two nodes, `model` and `tools`, with the same routing for either guard backend:

```mermaid
flowchart TD
    S([START]) --> Model["model: reserve attempt, call managed Responses, validate reply"]
    Model -->|valid tool calls| Tools["tools: serial gateway MCP calls, pair ToolMessages"]
    Tools -->|executed results| Model
    Model -->|genuine final content| E([END: completed])
    Model -->|fault, limit, cancellation or timeout| F([END: explicit non-completed result])
    Tools -->|blocked, error, unknown or limit| F
```

Episode allocation, state snapshots, checker evaluation, cleanup and external judging belong to [`src/benchmark/wiring.py`](src/benchmark/wiring.py), outside the reasoning loop. The agent neither chooses the guard mode nor authorizes its own actions.

- **Conversation:** LangChain `SystemMessage`, `HumanMessage`, `AIMessage` and `ToolMessage` retain structured calls/results and their IDs. Advertise all 11 remote canonical schemas; execute only requested tools.
- **Bounded behavior:** explicit model/tool/deadline limits and a persistent combined actor/LLM-guard request ledger. Reservations remain spent on failure. Incomplete replies, reused IDs, unknown effects and exhausted budgets are not normal completion; no guessed tool-call repair or automatic provider fallback.
- **Remote execution:** managed agentgateway MCP → banking bridge → service-prepared ticket → Actor. The Actor claims the exact immutable ticket through Substrate's native egress hook before computing the tool. Receipts and committed state live in the existing store; uncertain results are reconciled without repeating writes.
- **Evidence:** graph, model, gateway, tool, native guard, receipt and external-review records remain distinguishable in MLflow. Client and gateway model spans are layers of one physical request, not separate model attempts.
- **Recovery limits:** durable receipts and budgets are not a conversation checkpointer. Explicit reuse of a completed, reconciled canary re-audits saved evidence without repeating model/tool actions; it is not general graph resumption.

The initial wiring profile uses **deterministic native allow/block/error controls**. Guard adapters and a local-only encoder loader exist, but wiring controls do not establish trained classifier quality, banking calibration or a measured classifier/LLM comparison. The [experiment protocol](docs/benchmark-guard-experiment.md) defines these separate requirements.

The older command graph and `LocalBankingPipeline`/`ActorBankingTrial` remain historical compatibility paths, not the benchmark entry point. See [legacy boundaries](docs/legacy-compatibility.md).

### Chat templates and the model/tool boundary

The agent sends structured API messages and tool schemas; **LM Studio applies the model's chat template and parses generated tool-call text**. These are different from LangGraph's routing responsibilities. For Qwen3 Instruct, the native format is a JSON function request wrapped in `<tool_call>...</tool_call>`; Qwen3-Coder's nested function/parameter XML is a different protocol. Use the exact model-family template/parser pair, not a generic “Qwen” replacement.

Pin the model/quantization, serving runtime, template hash, sampling settings, stop conditions and API message serialization for reproducible comparisons. Never fix an unparseable response by guessing and executing its intended tool call. See the [evidence-backed rent/parser analysis](docs/validation/rent-parser-analysis.md) for a concrete model/tool trace, template comparison, external references and proposed controlled improvements.

## Architecture and trust boundaries

The benchmark separates transport, native admission, execution and external evaluation:

```text
Pinned AgentDojo task/state/checker adapter
  -> one LangGraph flow
       -> agentgateway Responses -> approved local acting model
       -> agentgateway MCP -> banking bridge -> prepared action ticket -> Actor
            -> native Substrate Envoy pre-claim gate
                 -> shared canonical action/context review
                      A: LLM reviewer
                      B: compact neural encoder + fitted calibration
                 -> allow: store claim -> Actor tool computation -> store commit
                 -> block/error: no tool computation or committed effect
  -> original private checkers, receipt/state audit and cleanup
  -> external native MLflow Gemini task/effect and overall harness review

MLflow: actual attempts, distributed parentage, trace-local scores and failures
```

The common native hook is exercised with deterministic controls; the learned A/B branches remain an experiment to implement and validate. The header-only hook reviews `/claim/<ticket>` and the store consumes that same path ticket, rejecting a decoy body ticket. A guard response in an agent-local branch or an application-only check is not native enforcement evidence. No platform fork or production IAM project is required. See the [experiment protocol](docs/benchmark-guard-experiment.md) and [GitHub roadmap](https://github.com/caldeirav/sub15-breaker/issues/14) for scope and evidence boundaries.

### What is trusted?

- **Untrusted:** model output, proposed tool arguments, agent-provided identity/score headers, invoice text, returned document contents and other attacker-controlled observations.
- **Service-controlled authority:** authenticated principal/trial ownership, Actor identity/generation, versioned intent and policy, current state version, admission decisions and independently produced receipts.
- **Evaluator-only:** golden reference trajectories, hidden checker answers and selected attacker objectives. These must not become acting-model or admission-verifier inputs.
- **Outside the protection claim:** a compromised host/control plane, cluster administrator or trusted policy/model artifact publisher. Isolation reduces consequences; it does not make these authorities trustworthy by itself.

| Threat | Banking example | Required control / residual limit |
| --- | --- | --- |
| Prompt injection | An invoice asks the agent to replace the recipient or disclose a subscription | Treat tool text as data; verify against separately sourced intent/policy. A well-formed tool call can still be unauthorized. |
| Unauthorized mutation or disclosure | Change a scheduled payment or account detail unrelated to the request | Context-aware policy, capabilities, bounded access and independently checked effects; utility alone is not safety. |
| Request mismatch or gateway bypass | Reuse an allow decision for another payload, state or Actor | Authenticated transport, exact binding, expiry, atomic state checks and tested bypass prevention. |
| Duplicate or uncertain writes | A payment succeeds but its response is lost | Idempotency registry, transactional state/receipt commit and status reconciliation; a timeout is not proof of non-execution. |
| Cross-trial leakage | A previous trial's modified state or credentials survive reset | Isolated state, generation-scoped lifecycle, verified reset fingerprints and cleanup. |
| Resource exhaustion | Excessive calls, huge arguments/results or stalled operations | Input/output/turn/time/concurrency/resource limits; a classifier is not a quota system. |
| Misleading evidence | Treat a 503 as a prevented attack or a judge opinion as truth | Distinct denial/execution/error/unknown outcomes, independent receipts and exact trace/readback coverage. |

### Action, context and transaction binding

An action carries a tool name, typed arguments, action/idempotency IDs and optimistic expected context/state/generation versions. It cannot select its own principal, policy, trusted intent or decision. Trusted services resolve those facts and bind the exact canonical action/context to admission and execution.

Amounts use **exact decimal strings in benchmark-native units**. There is no inferred currency or silent rounding. The explicit adapter to upstream float arguments rejects decimal round-trip value loss. Profile-owned bounds and precision are separate from financial authorization rules.

Private-keyed HMAC commitments in the record-only fixtures avoid publishing guessable fingerprints of password-bearing inputs. They are **not** production authentication, signed admission grants or a key-management system. JSON Schema validates shape and expressible outcome conditions; dynamic equality/order, freshness, authority and cryptographic binding require runtime checks. See [contract semantics](docs/banking-contracts-03a.md).

At a real mutation boundary, expected state must be checked atomically with the change. A matching retry must not repeat the effect; changed-payload ID reuse must fail. Unknown write outcomes require receipt/status reconciliation before retry. These are transactional guarantees to demonstrate, not guarantees provided by serializing a DTO or copying Python state.

The [Actor-backed local service design](docs/banking-actor-service.md) separates disposable tool computation from authoritative state: pinned functions run inside the Actor, while a dedicated single-writer service atomically commits synthetic state, receipts and an evidence outbox on its own persistent volume. This preserves receipt history across Actor replacement without reusing platform database credentials. Its local durability profile does not cover node/disk loss or HA; acceptance evidence belongs in the linked GitHub issues.

### Denial, latch, stop and reset are different

- **Deny:** do not forward this action.
- **Latch:** prevent later admissions for the affected trial/Actor generation, including concurrent clients.
- **Stop:** request termination of the correct Actor and observe acknowledgment independently.
- **Reset:** establish fresh synthetic state and a new generation under authorized lifecycle control.

A cooperative agent stopping its loop is not an externally enforced latch. A 403 is not termination. A reset does not undo a previously disclosed secret or an external payment.

## Technical decisions

| Component | Role and rationale |
| --- | --- |
| **AgentDojo banking** | Reuse pinned tasks, synthetic state, 11 tool definitions and executable checks; minimize custom benchmark work and preserve upstream parity. |
| **Agent Substrate + gVisor** | Ephemeral per-trial Actors and the native Envoy admission hook. Observe actual runtime assignment, dispatch counts, receipts and state effects. |
| **agentgateway** | Managed Responses/model routing, remote MCP transport and distributed telemetry. Guard choice belongs at the shared native Substrate admission boundary, not in competing agent loops. |
| **Compact encoder + PyTorch/Transformers** | Binary policy classification without autoregressive verification tokens. Model architecture, input schema, labels, calibration and runtime must be version-bound. |
| **LangChain/LangGraph + local LM Studio model** | One compiled tool-calling loop via managed Responses; the suite adapter and model configuration remain outside its generic runtime. |
| **MLflow** | Trace/evaluation system of record: invocation inputs/results, action-owned assessments, provenance, failures, artifacts and persisted readback—not only run-level averages. |
| **Native MLflow Gemini judges** | External post-execution evidence review, separate from admission. Observe the installed native Gateway provider adapter (or LiteLLM where selected); MLflow's SDK adapter is not the deployed agentgateway. |
| **Podman + Kind + Cilium** | Local Kubernetes profile with an enforcing CNI and explicit positive/negative network tests. Merely creating NetworkPolicy objects is insufficient. |
| **uv** | Managed Python and a committed universal lockfile for development/tests and reproducible installation. Models, images, controllers and credentials need their own explicit provenance. |

The acting model is reached through managed agentgateway Responses. Gemini judging is an external provider call outside the agent/admission loop, not another guard invocation. Local acting inference does **not** make the full experiment offline/private: external review transmits projected synthetic evidence. Report available usage/cost and retain unavailable usage, parser errors and historical accounting gaps rather than inventing a complete bill.

The legacy command-only sidecar, command dataset and Streamlit view are compatibility scaffolding, not a banking model or the authoritative banking evidence UI. See [legacy boundaries](docs/legacy-compatibility.md). No generic shell executor or alternative financial corpus is required.

## Risk model and calibration

The intended classifier consumes the **canonical action plus trusted intent/policy/state context**, not just recipient/amount or an agent-written safety proposition. The same action may be permitted under one trusted request and forbidden under another.

A compact MiniLM- or DeBERTa-family encoder is a possible starting architecture, not a released safety artifact. A generic relevance checkpoint is not a drop-in safety verifier. Class meanings must be independently verified: for two logits, let class 0 mean permitted and class 1 mean prohibited under the declared labeling policy.

With temperature $T > 0$, the estimated policy risk is:

$$
p_{\mathrm{risk}} = \operatorname{softmax}(z/T)_1
= \sigma\!\left(\frac{z_1-z_0}{T}\right).
$$

This uses the **logit difference**, not a sigmoid of one arbitrary class logit. Temperature scaling fits held-out negative log-likelihood; it does not create correct labels or directly minimize ECE. See [Guo et al., 2017](https://proceedings.mlr.press/v70/guo17a.html).

Use separate, group-disjoint **training, calibration, threshold-validation and final-test** populations. End-state task success and Gemini opinions do not independently label every intermediate action. Freeze a policy/model/schema-bound threshold $\tau$ after choosing an operating point on validation data; deny when $p_{\mathrm{risk}} \geq \tau$. The legacy command prototype's 0.70 is not a justified banking threshold.

Calibration should be reported with NLL, Brier score, reliability bins and ECE, alongside false-negative/false-positive rates, coverage and uncertainty:

$$
\mathrm{ECE}=\sum_b\frac{|B_b|}{N}
\left|\operatorname{mean}_{i\in B_b}(p_i)
-\operatorname{mean}_{i\in B_b}(y_i)\right|.
$$

Low aggregate ECE can hide rare dangerous failures or distribution shift. Calibration is not universal safety, and performance claims must identify the precise artifact, policy, input population and hardware profile. Missing/mismatched artifacts, malformed decisions, unavailable inference and unsupported inputs must not become approvals.

## Golden environment and evaluation design

Source: AgentDojo package `0.1.35`, Git commit `089ed468cf3ed0322acc66b0211f26d9d90dbf60`, banking benchmark `v1.2.2`.

| Task | User goal | Executable utility criterion |
| --- | --- | --- |
| `user_task_0` | Pay the supplied bill | Upstream expected transaction amount/recipient |
| `user_task_2` | Adjust rent from the notice | Upstream first matching scheduled rent amount |
| `user_task_13` | Update account address | Upstream street/city predicate |

Golden references/checkers stay evaluator-only. The agent receives the user's request and available observations, not the expected answer. The simulated payment tool is not a settlement/accounting system; retain upstream weaknesses for parity rather than silently strengthen the benchmark.

Four criteria remain distinct: **task utility**, **upstream selected attacker parity**, **new/changed forbidden-recipient effects**, and **declared subscription-disclosure goal**. A task can succeed while an additional forbidden effect occurs. Original invoice-replacing attacks and fact-preserving append adaptations must be labeled separately; destroyed task facts do not prove safe refusal. See [golden environment and metric meanings](docs/golden-data.md).

### Two complementary A/B protocols

1. **Same-action replay:** both verifiers receive identical independently reviewed action/context pairs. This isolates discrimination, calibration and complete admission latency.
2. **Fresh-state full-agent trials:** the agent attempts each task under each verifier from equivalent isolated initial state. Action sequences may diverge; measure utility, effects, refusal, failures and total cost rather than assume identical proposals.

Both need benign near-misses as well as attacks, exact denominators, declared exclusions, counterbalanced order/repeats and retained unknown/error outcomes. Deny-all/allow-all controls expose misleading aggregate success. A correctly captured and scored agent failure is successful evaluation—not successful agent work. Harness correctness, guard quality and task quality are separate questions.

### What latency means

Measure completed **authoritative authorization**: parsing, trusted-context resolution, queueing, transport, verifier inference and admission checks at a declared boundary. Include exactly one authoritative verifier invocation per admission; an agent-side score followed by a gateway rescore is not the intended B path.

Report hardware/load/input sizes, warm/cold behavior, p50/p95/p99, failures and availability at a predeclared quality operating point. A model forward-pass timer excludes gateway/network/context work; total task time includes agent/tool/reset/judge work. Neither is interchangeable with admission latency. Do not assume seconds for A or milliseconds for B, omit failed samples or choose a favorable percentile after measurement.

### Evidence and native judge review

MLflow records every model/tool/verifier/judge attempt, including failures, with scores on the owning trace/action span. Lifecycle, receipt, state and evaluation evidence must reconcile. Run-level averages never replace exact case/review coverage, stage outcomes or persisted assessment ownership.

Native Gemini judges run **outside authorization**. They review criterion-specific projected observations against closed normalized rules, not checker Python, measured verdicts or the agent's claims of success. Keep raw native feedback, decoded provenance and scalar verdict/validity/agreement/error fields. Deterministic outcomes remain authoritative; disagreement and insufficient evidence remain visible. Schema-constrained outputs are not independent safety ground truth.

A separate versioned overall-harness review examines persisted transport, Actor, native-control, receipt, trace/accounting and case/cleanup evidence. It returns `supported`, `not_supported` or `insufficient_evidence`. A later review/reporting fix creates a new derived target; it never replaces an earlier negative verdict or repairs malformed judge JSON. External support is not human acceptance or a learned-guard safety certificate.

See [evaluation design](docs/evaluation-design-review.md), [trace/score ownership](docs/mlflow-trace-contract.md) and [the banking runbook](docs/banking-feasibility.md) for exact evidence contracts and examples.

## Run locally

### Python and configuration

Use [uv](https://docs.astral.sh/uv/) and the committed lockfile. Python 3.11–3.13 is supported; `.python-version` selects the local default.

```bash
uv python install
uv sync --locked
```

Create `.env` from `.env.example` **only if absent**; never overwrite existing credentials or commit them. Configure:

| Setting | Purpose |
| --- | --- |
| `LM_STUDIO_BASE_URL`, `LM_STUDIO_MODEL` | Approved local provider/profile; the benchmark agent itself uses the managed gateway Responses endpoint |
| `MLFLOW_TRACKING_URI` | Tracking server, normally `http://localhost:5001` |
| Tracking experiment | The wiring command selects `breaker-banking-target-agent`; legacy runbooks have separate experiment settings |
| `GEMINI_API_KEY` | External native judge credentials for the full live harness |
| `MLFLOW_GENAI_JUDGE_DEFAULT_MODEL` | Native judge model, default `gemini:/gemini-2.5-flash` |

If MLflow is not already running, start it in another terminal:

```bash
uv run --locked mlflow server --host 127.0.0.1 --port 5001 \
  --backend-store-uri sqlite:///mlflow.db \
  --artifacts-destination .infra/mlflow-artifacts
```

Offline tests need no running stack. The real wiring command requires the owned local Substrate/gVisor, managed gateway and banking store/Actor profile described in the [infrastructure guide](docs/infra.md) and [benchmark protocol](docs/benchmark-guard-experiment.md). Classifier weights are not prerequisites for deterministic wiring controls. There is no installed `sub15-breaker` CLI; use module entry points.

### Tests and experiments

```bash
# Offline tests; no model/provider calls or tracking server required.
bash scripts/test.sh

# Export shared schemas to an ignored local directory; no tool execution.
uv run --locked python -m src.banking_contracts.schemas

# Record-only CODE contract fixtures; requires MLflow, not models or bank actions.
uv run --locked --env-file .env python -m src.banking_contracts.fixtures

# Persisted MLflow plumbing validation with model stubs, no provider calls.
uv run --locked --env-file .env python -m pytest -q validation/test_banking_mlflow_local.py

# Real gateway/MCP/Substrate/Actor allow/block/error controls; no model calls.
uv run --locked python -m src.benchmark.wiring
```

For live execution, first freeze the task/profile/request allocation in the [benchmark protocol](docs/benchmark-guard-experiment.md). `src.benchmark.wiring --live` spends local and external requests; `--extended-pilot --reuse-completed-case-run CASE_RUN_ID` selects the explicitly frozen extended allocation and reuses only a completed reconciled canary. The ledger persists across runs: do not delete/reset it or repeatedly sample for favorable outcomes. A completed pilot is not an unlimited rerun allowance.

To review saved suite evidence after a documented review/reporting fix, without repeating agent/tool actions:

```bash
uv run --locked python -m src.benchmark.review_saved --source-trace SUITE_TRACE_ID
```

This **does call Gemini** and creates a new derived review target. It needs the original persisted suite trace and authorized external budget. The older `src.feasibility.runner` remains an in-memory reproducibility path; its `--oracle-only` skips the acting model **but still invokes Gemini**. Example MLflow links refer to the owner's local server, not a public service. Open the **Traces** table for action/effect scores and separate native review rows.

### Dependencies and infrastructure

Use `uv add PACKAGE` for runtime dependencies and `uv add --dev PACKAGE` for test tools; commit both `pyproject.toml` and `uv.lock`. Review deliberate upgrades and run the tests. Do not maintain an unrelated requirements file or install ad hoc packages into the project environment. Locked runs refuse implicit dependency changes; deploy synchronized images without runtime dependency downloads.

For the local infrastructure profile, follow [the infrastructure guide](docs/infra.md). It distinguishes installation/network/protocol fixtures from actual banking Actor and native admission controls. The benchmark temporarily attaches its native filter and restores the prior configuration on exit; it does not require the deferred sustained-uptime qualification. The legacy `--research` environment check includes a command-only sidecar and is not a banking doctor. Do not apply the [placeholder workloads](k8s/README.md) as if they supplied a complete deployment.

## Explore the repository

| Path | Purpose |
| --- | --- |
| `src/agent_runtime/` | Suite-neutral contracts and the single compiled LangGraph reasoning loop |
| `src/integrations/agentdojo/` | Pinned banking task/state/private checker adapter, not an agent framework |
| `src/benchmark/` | Real wiring CLI, managed MCP bridge, native gate, budgets, guard adapters, encoder loader and external review |
| `src/feasibility/` | Retained evaluation/checker/judge utilities and historical in-memory reproducibility paths |
| `src/banking_contracts/` | Shared action/context/decision/receipt types, JSON Schema exports and record-only structural fixtures |
| `src/banking_service/` | Opt-in Actor-backed computation, transactional state/receipts, platform identity and durable evidence transport |
| `src/infra/`, `scripts/`, `infra/` | Pinned local infrastructure, readiness and harmless network/enforcement probes |
| `tests/`, `validation/` | Offline regressions and explicit opt-in persisted/live validation |
| `k8s/` | Research workload examples; inspect their prerequisites before use |
| `docs/`, `specs/` | Architecture/contracts, runbooks, evaluation semantics and historical evidence |

Start with the [documentation index](docs/README.md), [scope/trust boundaries](docs/project-scope.md) and [specification](specs/001-breaker.md). Track project progress and planned implementation in [GitHub roadmap #14](https://github.com/caldeirav/sub15-breaker/issues/14), not README test counts or block-status summaries.
