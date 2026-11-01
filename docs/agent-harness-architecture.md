# Agent runtime and evaluation harness boundaries

AgentDojo supplies a valuable **test suite**: pinned tasks, synthetic state,
tools, attacks and executable checkers. Its agent pipeline is not the target
orchestrator. Retain the suite while replacing the agent integration with a
small LangChain/LangGraph runner and gateway-mediated model/tool transport.

## Separate responsibilities

```text
experiment harness
  -> suite adapter: task, environment provisioning, reset and private checkers
  -> AgentRunner: public task + tool capability + trusted execution reference
       -> LangGraph / LangChain messages
            -> agentgateway Responses -> approved local model
            -> agentgateway MCP -> domain tool bridge -> Actor/store
  <- neutral RunResult: final response, terminal status, usage and evidence refs
  -> evaluator: private initial/final state + receipts + pinned checkers
  -> persisted MLflow evidence and separate completion/utility/safety scores
```

The harness controls episode lifecycle, outer budgets, deadlines/cancellation,
provenance and evaluation. The runner controls one reasoning loop and reports
explicit termination. The domain backend validates authority, prepares stable
actions, executes tools and reconciles effects. None of these roles can treat
trace metadata or model-supplied context as authority.

The model is a configured dependency, not an architecture fork. Keep the current
approved local model and explicit gateway endpoint. Do not make model tuning,
downloads, paid judges or a utility win rate prerequisites for the first running
harness slice. Provider compatibility, bounded attempts and truthful failure
termination still matter.

## Small contracts, not another agent framework

Start with three boundaries:

1. **AgentRunner** accepts a public task input, a run-scoped service/capability
   context and limits. It returns a neutral result with final content, terminal
   status, usage/counters and trace/action/effect references.
2. **Environment adapter** provisions and resets an episode, supplies public tool
   schemas/endpoint references, and retains private initial/final state. Use
   existing Actor/store lifecycle services rather than invent another executor.
3. **Evaluator** consumes the result and private environment evidence after the
   run. It invokes the pinned upstream predicates and records outcomes/errors.
   It never supplies hidden solutions or checker verdicts to the agent.

Use LangChain messages inside the concrete runner. Do not require them, AgentDojo
environment objects or LangGraph checkpoint internals in the harness result
contract. Use LangGraph runtime context to inject services; keep credentials,
policy resolution and trusted principal/state references out of prompts and
serializable graph state. Runtime-context injection is not authentication by
itself.

Avoid a plugin registry, multi-agent hierarchy, general shell executor or a
custom replacement for LangChain/LangGraph. Implement the interfaces needed by
one end-to-end episode, then extend them only when another real adapter needs it.

## Dependency direction

Proposed module boundaries:

| Boundary | May depend on | Must not depend on |
| --- | --- | --- |
| `src/agent_runtime/` | LangChain/LangGraph, model/MCP transport, neutral contracts | AgentDojo, suite task IDs/checkers, `src/feasibility`, concrete banking trial classes |
| `src/harness/` | Neutral runner/environment/evaluator contracts, budgets, evidence | AgentDojo pipeline classes or the concrete LangGraph implementation |
| `src/integrations/agentdojo/` | Pinned AgentDojo loaders/checkers, accepted metric semantics, domain adapters | Driving an alternative hidden agent loop |
| Banking MCP/backend adapter | Canonical banking contracts, Actor/store services, pinned tool implementations where executed | Host-tool fallback or model-selected authority |

Enforce these boundaries with import tests and installation profiles. A runtime
that avoids `import agentdojo` but still installs it through mandatory project
dependencies is only partly decoupled. Provide a minimal runtime dependency
group/image; keep suite/evaluation dependencies in the adapter/backend profile.

Existing coupling explains why a fresh boundary is preferable to extending the
interim classes: `LocalBankingPipeline` subclasses AgentDojo's
`BasePipelineElement`, and `ActorBankingTrial` subclasses `BankingTrial`, whose
constructor creates a host `FunctionsRuntime`. Preserve those implementations as
historical regressions; do not make the new runner inherit from them. Extract or
reuse checker/metric behavior through the adapter instead of rewriting its
meaning. Executing pinned AgentDojo tools inside the isolated domain backend is
an intentional dependency, not an agent-runtime dependency.

## First vertical slice

Build one supported command that provisions a fresh pinned banking episode,
invokes the concrete LangGraph runner through the managed model/MCP gateway,
receives genuine final output or an explicit failure, reconciles receipts,
scores with the original checkers and cleans up. Discover all11 canonical tool
schemas; execute only the tools the model requests. Start with the already
approved `user_task_0`, not a new financial corpus or a fabricated golden answer.

First prove the contracts offline with a scripted model and tiny fake
environment. These are unit fixtures, not additional benchmark tasks. Verify
that the generic runner/harness import and execute without AgentDojo installed.
Then exercise the real gateway/MCP/Actor path without inference, followed by one
predeclared bounded local canary in the existing compatibility budget. Avoid a
second standalone serving campaign that must be repeated on the final harness.

Completion, task utility, safety and infrastructure reliability are separate:

- Normal completion needs genuine final assistant content, paired tool results,
  no pending/invalid calls and no unresolved effects.
- Provider, budget, cancellation or uncertain-write faults terminate explicitly;
  a canned apology is not successful completion.
- Upstream utility/security predicates retain their original behavior and
  orientation. Refusal/clarification and unknown/evaluation errors remain
  distinguishable from a negative score.
- The owner-deferred two-hour soak is a separate reliability check. Functional
  startup must still verify current identity/configuration, authentication,
  schema compatibility, limits and persisted telemetry. Do not bypass those
  checks or relabel the strict full qualification as passed.

Instrument the compiled graph before construction with native MLflow tracing;
link gateway spans with W3C context and verify persisted parentage and CODE score
ownership. Keep exact attempt/usage accounting, errors and schema-aware masking.
Disable duplicate lower-level model autologging. For async manual spans, follow
the documented inline-tracer/separate-task requirements. Checkpoint replay must
not reset budgets or reissue an uncertain mutation under a new action identity.

The larger baseline remains the existing three-task slice and one frozen
nine-trial completion matrix. Preserve the original failed runs and spent
budgets. Native Gemini evaluation remains an optional separately authorized
post-run evaluator, not part of this local-only completion gate.

References checked through Context7: [LangGraph runtime context](https://docs.langchain.com/oss/python/langgraph/graph-api),
[LangChain MCP tools](https://docs.langchain.com/oss/python/langchain/mcp/tools),
[MLflow LangGraph tracing](https://mlflow.org/docs/latest/genai/tracing/integrations/listing/langgraph).
AgentDojo parity is anchored to the repository's pinned commit, not latest-doc
agent-pipeline behavior. Delivery scope and dependencies belong in GitHub #31.
