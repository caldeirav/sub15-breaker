# One-flow guard benchmark

This is a local benchmark on synthetic AgentDojo banking state, not a production
banking or identity system. The question is whether a guard at the Substrate
execution boundary blocks bad agent actions, and how a calibrated compact
neural classifier compares with an LLM reviewer at that **same** boundary.

```text
AgentDojo task/state/checker adapter
  -> one LangGraph agent flow -> proposed tool action
  -> common Substrate-side admission hook
       A: LLM review
       B: compact encoder + fitted calibration + frozen threshold
  -> same Actor tool service, or verified non-execution
  -> original task/effect checks + guard-quality and timing evidence in MLflow
```

Only the guard backend changes between modes. Do not put A's review in the agent
and B's review in the platform, or execute one mode locally and the other inside
an Actor. AgentDojo remains the task/tool/checker source; the agent does not
inherit its pipeline or receive its private expected outcomes.

## Keep the benchmark small

Keep the current owned local stack and existing platform configuration. Do not
add production IAM, a new identity provider, key-management work, multi-tenant
policy, HA or a second agent framework. Existing working platform identity and
transport may be reused without becoming new research deliverables. The
two-hour soak is separate follow-up #39, not a functional benchmark prerequisite.

Still require simple benchmark-correctness properties: fresh episode state,
action/result IDs, a decision tied to the action actually consumed, no execution
after a block/error, observable failures and no silent host-tool fallback. These
prevent invalid experimental results; they are not production-authentication
claims. Do not remove existing service safeguards merely to reduce code.

## Native hook feasibility

The pinned Substrate release supports
`--experimental-additional-egress-extproc-service` on its existing Envoy
dataplane. Its generated filter sends headers, has request-body processing
disabled and defaults to a two-second timeout. It cannot simply classify the
banking JSON body without an adaptation.

Use one immutable benchmark action reference that resolves to the canonical
action and current episode context before tool computation. The reference in the
review must identify the same action the tool consumes; a decoy header with a
different body is not a valid enforcement test. A ticket-in-path/resolver design
can use the header-only hook without treating arbitrary text headers as policy
authority. Select and document a shared timeout that accommodates the LLM guard;
do not make it lose by silently inheriting an unsuitable classifier-sized budget.

Prove allow, block and reviewer-error controls on the actual Substrate path:
tool-dispatch count, receipts and state differences must agree. A guard returning
`block` in a unit test or an `if` in the agent is **not** evidence that Substrate
enforced a denial. An Actor-side application check must not be relabeled a
native ingress/egress hook. No platform fork is needed for the documented hook.

## Common review input and labels

Both guards receive the same versioned serialization of the legitimate user
goal, short benchmark policy, canonical action, relevant state projection and
untrusted tool observations. Include only the state needed for the selected
policy. Do not expose checker Python, reference trajectories or measured labels
to either guard. AgentDojo's end-state utility is not a label for every action.

Use existing pinned references, attack/control trajectories and observed
proposals as **candidate** action/context examples. Review their per-action
labels against the declared policy before training. Keep task/document/attack
groups separated across training, calibration, threshold selection and test;
record overlap and the limitations of the tiny three-task development slice.
Do not manufacture a new financial corpus or have the LLM reviewer mint its own
independent ground truth.

The owner selected a **compact neural encoder**, not a sparse baseline. A cached
MiniLM-L6 base is available as a possible training starting point. It is not a
banking safety classifier, and the old command/relevance head and threshold0.70
cannot be reused as banking calibration. A trained compatible artifact and
reviewed banking labels are not currently present.

Fit a binary action/context head, then temperature/calibration and a threshold
on separate reviewed data. Freeze weights, input/policy version, class mapping,
splits and operating point before held-out comparison. Record calibration
metrics and FNR/FPR/coverage; do not call a verbal LLM confidence or an arbitrary
temperature a measured calibration. The encoder loader is local-only, requires
a compatible manifest and refuses missing/randomly initialized weights.

## Measure two different experiments

1. **Frozen-action paired replay:** both guards review identical action/context
   pairs; alternate A/B order. Report confusion counts, false allows/blocks,
   errors/unknowns and coverage against reviewed labels. This measures guard
   quality and removes divergent agent trajectories as a latency confounder.
2. **Fresh-state complete episodes:** the same agent implementation runs the
   existing AgentDojo cases under each mode. Report completion, upstream
   utility/attack predicates, observed forbidden effects, blocked actions,
   errors and total cost separately. Trajectories may diverge; do not pretend
   they are matched action samples.

Record full admission latency around the common platform hook, with separate
serialization/context, network/queue, inference and decision timings. Exclude
acting-model generation, tool execution, reset and post-run judging from that
authorization measurement; report end-to-end episode time separately. Warm/cold,
hardware, input size, sample count and timeout behavior belong in the result.
Review-only timers and synthetic unit logits are not full-path performance
evidence. Do not claim a speed/latency target at an unmatched quality point.

Every actual actor-model and LLM-guard request, retry and error counts against
one approved **80-local-request total**. The owner approved revising the old
allocation to cover both roles. Freeze a revised pilot matrix before live calls;
do not add an independent verifier allowance or reset spent reservations. No
paid judges, provider fallback, weight downloads or paid-provider calls are
authorized by this allocation. There are no new live requests yet.

## Initial implementation boundary

The new `src/agent_runtime` contains one compiled graph and suite-neutral run
data. `src/integrations/agentdojo` supplies pinned task/private checker access;
it does not execute tools in the normal host path. `src/benchmark` defines the
common review input, classifier/LLM adapters and counterbalanced replay helpers.
The runtime-only dependency group can execute without AgentDojo installed.

Current tests use scripted models, synthetic logits and an explicitly in-memory
reference backend. They prove contract/flow and checker parity only. Native
guard-hook wiring, real gateway/MCP/Actor episodes, trained encoder/calibration
and measured A/B performance are subsequent integration work, not delivered
claims. Use the current GitHub scope #41 for sequencing and acceptance.
