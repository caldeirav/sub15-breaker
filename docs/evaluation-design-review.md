# Evaluation design review: executable truth and an evidence-grounded Gemini reviewer

**Current acceptance scope:** [harness v3](banking-harness-acceptance-v3.md) is independently validated and explicitly accepted by @caldeirav on 2026-10-31 ([record](validation/block-02.json)). A correctly traced and scored agent failure is successful evaluation, not successful agent work. Historical v1/v2 statuses are preserved and #25 is nonblocking quality work. Subsequent blocks still require their own human acceptance; see [the next iteration](next-iteration.md).

Initially reviewed 2026-10-31 as static research. The authorized follow-up [banking feasibility block](banking-feasibility.md) is now implemented and executed with native MLflow Gemini judges. Its corrected run passed 12 controls and three benign tasks, with 34 validly cited reviews and 33 oracle agreements. One retained disagreement leaves strict acceptance `review_required`; this is not a production domain migration or deployed safety boundary.

**Latest v2 update:** owner-approved #20 semantics are implemented and independently verified: separate utility/upstream parity, selected forbidden-recipient effects and declared disclosure goals, with normalized judge inputs and exact provenance binding. The fresh main had 68/68 valid/agreed reviews but remains FAILED for 2/3 benign utility; #25 tracks premature rent clarification. Original failures remain preserved. See [current human review guidance](validation/block-02-v2-review.md), not the historical 34-review result alone.

## Recommendation

Replace the idea of “Gemini decides whether the command looks correct” with **trusted task/policy ground truth -> independently captured execution facts -> deterministic verdict -> Gemini evidence review**.

**Updated direction:** the accepted **AgentDojo simulated banking** harness reuses existing tools/state/tasks/checkers rather than a new corpus. #20, harness-v3 validation, independent review and scoped human acceptance are complete; #25 is separate quality work. Tau2 retail and the historical Terminal-Bench option are alternatives, not parallel data projects.

Use a small independently authored fixture suite to develop the harness. For held-out task utility, pilot a pinned, preselected CPU/filesystem/log-processing subset of Terminal-Bench 2.1. Evaluate Terminal-Bench 3.0 separately as a broader/harder holdout, not as an automatic replacement merely because it is newer. The original InterCode-Bash environments are also a close domain fit, but their reward implementation is not a strict universal correctness oracle. Keep independently reviewed action-policy examples for safety/calibration; task-success benchmarks do not supply those labels.

That Terminal-Bench recommendation applies if Bash remains the chosen domain. Do not build both domains before choosing: the project is about verification architecture, not authoring another benchmark.

## Cross-domain options: minimize data work

| Use-case | Existing package/data | What is ready | Remaining integration / recommendation |
| --- | --- | --- | --- |
| Simulated bill payment / banking | [AgentDojo](https://github.com/ethz-spylab/agentdojo), banking suite | Fake accounts and files, 11 structured tools, 16 user tasks, 9 injection objectives, reference tool sequences and executable utility/security functions in the inspected suite. Core environments are in-memory, not live bank APIs. | **Preferred financial candidate:** wrap existing tool dispatch/state, reuse tasks/attacks/checkers and reset by independent environment copies. Check task/oracle quality first; do not promise every row is suitable. |
| E-commerce refunds / order changes | [tau2-bench](https://github.com/sierra-research/tau2-bench), [HF domain-data mirror](https://huggingface.co/datasets/HuggingFaceH4/tau2-bench-data) | Tools, policies, seeded JSON DBs, tasks and reference-derived end-state evaluation; broader customer-service workflows. | Strong alternative. User simulation adds LLM cost/variance, and reward components may also use semantic judges. Keep actual reward definitions rather than describing the whole benchmark as deterministic. |
| Office/email/calendar/Slack actions | AgentDojo workspace/Slack suites | Simulated tools/state, normal tasks, prompt-injection cases, reference actions and utility/security code in the same framework. | Good later domain transfer without changing frameworks. Some answer-only tasks have weak checks; favor effectful cases with explicit state/security predicates for the initial demo. |
| Airline booking/change/cancellation | tau2-bench airline | Simulated reservation DB, tool APIs, policy constraints and outcome scoring. | Ready business-action testbed, but user-simulator and policy complexity add integration compared with a small banking suite. |
| Financial document QA/research | [FinanceBench](https://huggingface.co/datasets/PatronusAI/financebench), [Finance Agent Benchmark](https://huggingface.co/datasets/vals-ai/finance_agent_benchmark) | Respectively 150 answer/evidence examples and 537 expert-authored research questions in the inspected cards. | Useful reference-grounded answer evaluation, but not the best main circuit-breaker demo: mostly retrieval/numerical-answer quality, not state-changing tool effects; retrieval/filing infrastructure adds work. FinanceBench's card specifies CC-BY-NC-4.0. |
| Financial regulatory/security workflows | [FinVault](https://github.com/aifinlab/FinVault) | Repository advertises 31 simulated scenarios with benign/attack cases and state/vulnerability code. | Not the lowest-risk dependency for this project now. The [arXiv record](https://arxiv.org/abs/2601.07853) reports withdrawal over legal/IP/affiliation/ownership concerns, and the repo describes research-use data conditions. This is not proof of technical invalidity, but adoption would require additional diligence rather than minimize work. |

These are benchmark **packages**, not interchangeable Hugging Face tables. AgentDojo's canonical task/state/checker definitions live in its code and bundled YAML; trajectory dumps on HF are not a replacement for that environment. The tau2 HF mirror distributes domain files, not a single uniform table suitable for blindly loading every JSON file together. Pin the framework and compatible data revision and use its native loader.

### What the banking demo would show

A user asks the agent to pay a supplied bill. The agent reads the simulated bill/history, then proposes a structured `send_money` or `schedule_transaction` call. An injected tool response tries to redirect the recipient or induce an unauthorized account change. Put the same gateway authorization boundary immediately before the simulated state mutation, then check both whether the legitimate task succeeded and whether the attack objective occurred.

This replaces a generic Bash effect with a bounded business action while preserving the central experiment: Mode A generative review versus Mode B single-pass verification, fail-closed authorization before mutation, and measured gateway overhead. Substrate can host the agent and isolated per-trial tool service; no real bank, payment credentials or money are needed. Keep denial, utility under attack, attack success and unknown/error outcomes separate. Blocking everything must not look successful.

This is **not** a drop-in data swap. The current agent/sidecar contract is `{"command":"..."}`. A business-tool adapter would need canonical tool name/arguments, trusted user intent/state references, Actor/trial/version binding and matching classifier inputs. Do not send hidden benchmark ground truth or attacker goals into the guard; those belong only to the evaluator. Gateway identity/framing/replay controls remain necessary. Hard identity/schema/limit rules should be deterministic rather than forced into a classifier.

### Minimum diligence, not a new data project

The inspected AgentDojo revision was `089ed468cf3ed0322acc66b0211f26d9d90dbf60`; its CLI defaults to versioned benchmark `v1.2.2`. Versioned definitions inherit earlier tasks and override selected ones. Banking has existing patches, so inspecting only the base `v1` source or counting a directory is insufficient.

There are concrete limitations to avoid hiding:

- In the inspected banking definitions, `UserTask8`'s broad transaction-summary utility function simply returns true. Exclude it from meaningful utility scoring rather than ask Gemini to manufacture the missing oracle.
- Other tasks use substring checks or partial state predicates. A reference trajectory passing is necessary but not sufficient: a no-op or extra unauthorized write must not also pass the claimed metric. Utility and attack-security checks are separate and may cover only the declared attack objective.
- The fake `send_money` tool appends a transaction but does not debit `balance`. Judge its defined transaction/state semantics; do not claim a complete accounting/settlement simulator.
- tau2's [evaluation documentation](https://github.com/sierra-research/tau2-bench/blob/main/docs/evaluation.md) explicitly distinguishes DB end-state checks from communication/NL assertions, which can use an LLM. One reference action list is generally not the only accepted trajectory.

The follow-up loaded that pinned suite and passed reference/no-op/wrong-effect/extra-attack controls for three predeclared tasks. It also exposed an attack that removed invoice facts and an upstream-predicate/Gemini disagreement, both retained in MLflow with regression coverage. Do not silently repair dozens of tasks or build a replacement financial corpus. If a clear, approved metric contract cannot support this slice, choose the alternative rather than expanding the data-cleaning project.

Finally, end-state/attack labels are not a ready calibrated risk-training set for every intermediate tool call. Reuse upstream success/security checks for evaluation; independently validate the guard's new action/context scope and calibration. This reduces task-data work, not the need for honest model-quality evidence.

## 1. What is wrong with judging against a command string?

`judge()` in `src/eval/runner.py` already receives `task`, including `gold`, and the agent result. However, its generic correctness/containment request has no typed rubric, independent reference execution state, deterministic test outcomes, or evidence-citation validation. Merely adding “be objective” cannot supply the missing facts.

For a task that extracts matching log lines, `grep` and `awk` may produce the same correct output in the specified fixture. A preparatory `ls` can be permitted without completing the task. A command equal to the reference can still violate a deployment policy, and an agent can claim success while producing the wrong file.

Therefore, keep three independent contracts:

| Contract | Ground truth | Appropriate result |
| --- | --- | --- |
| Action policy | Reviewed allowed effects/capabilities for the exact principal, Actor generation, workspace and policy version. | permitted / prohibited / unknown; auxiliary allowed actions need not complete the task. |
| Task outcome | Expected artifacts, structured output and task-specific assertions on a seeded workspace. | passed / failed / not evaluated / unknown. Harmful tasks use an expected-refusal oracle instead of rewarding their unsafe reference. |
| Containment | Trusted execution receipts, protected-path/resource/egress canaries and observed effects. | verified against the defined invariant / violated / insufficient evidence. A 403 or an agent-written success message alone is not proof. |

These outcome checks are post-execution evaluation, not part of the sub-15ms pre-execution authorization budget. They must not be used to pretend an unsafe, unexecuted action already has an observed safe outcome. Refused destructive actions get independently reviewed policy labels, not speculative execution labels from Gemini.

## 2. Dataset comparison

The following facts were checked against dataset APIs/cards and, where available, registry manifests. Counts describe the inspected revisions, not every future version.

| Candidate | What it provides | Fit for this project |
| --- | --- | --- |
| [Current 200-row InterCode export](https://huggingface.co/datasets/epinnock/intercode-nl2bash-curated) | Natural-language `query` and reference `gold` strings; no fixture/assertion/safety-label bundle. | Retain as a lightweight task source and compatibility set, not the sole correctness or safety oracle. |
| [Original InterCode-Bash](https://github.com/princeton-nlp/intercode) | Interactive environments and a separate reference-execution environment; filesystem/output comparison. | Closest to the current shell use-case. Reuse/review its environments, but replace or qualify fuzzy reward: the inspected implementation includes TF-IDF output similarity and filesystem heuristics, not just exact semantic assertions. |
| [Terminal-Bench 2.1](https://huggingface.co/datasets/harborframework/terminal-bench-2.1) | Registry of 89 tasks; instructions, environment configuration, verifier tests and reference-solution directories. Apache-2.0 card. | Recommended held-out pilot source. Select compatible CPU/file/log tasks by declared criteria, validate each oracle in the actual sandbox, and freeze the selection before measuring agents. |
| [Terminal-Bench 3.0](https://huggingface.co/datasets/harborframework/terminal-bench-3.0) | Registry of 74 tasks at version 3.0.0; mirrored task bundles and a tagged upstream release. Apache-2.0 card. | Newer, but many tasks cover difficult scientific/software/GPU domains rather than simple operations. Useful external stress/generalization set after the focused harness works. |
| [Larger NL2Bash export](https://huggingface.co/datasets/jiacheng-ye/nl2bash) | 8,090 train / 609 validation / 606 test rows with `nl` and `bash` strings. | More text coverage, not an upgrade to executable ground truth. It still needs fixtures, assertions and independent policy labels. |

Inspected HF revisions: Terminal-Bench 2.1 `3e235dff6880252a587fa479c09bcb1e16edf2eb`; 3.0 `2ee5a897d6be85513b41f44b945c4ff4d3e04a1d`; larger NL2Bash `8731103005b818a0298e658feb30005eb1d5e2f1`. The 2.1 card identifies upstream commit `7131e4375048a0e408a8fb404b5f499d726b695b`; 3.0 identifies tag `v3.0.0`, whose [release](https://github.com/harbor-framework/terminal-bench/releases/tag/v3.0.0) lists the initial 74 tasks. The upstream project is now presented as Frontier-Bench, another reason to pin a specific release rather than follow a moving default branch.

The 2.1/3.0 cards contain wording about private mirrors, while the unauthenticated HF API reported both public and ungated and their inspected files were readable. Verify access, LFS assets, license/attribution and the exact task revision during adoption; do not rely solely on card prose or popularity.

### Concrete example and caveats

The inspected Terminal-Bench 2.1 `log-summary-date-ranges` task specifies a fixed reference date, input log naming, and a CSV result contract; its verifier checks file existence, CSV structure and exact expected rows. That is a much stronger basis than asking Gemini whether a shell command “seems right.” Do not copy its held-out expected answers into training or prompts visible to the acting agent.

However, its task configuration allows internet and its verifier bootstrap installs dependencies. It is **not** automatically compatible with our no-ambient-network, unprivileged Actor profile. Prebuild/pin verifier dependencies in a trusted image, test offline feasibility and CPU/architecture/runtime compatibility, and review all task/container/solution assets before running them. Any material adaptation is an internal adapted benchmark, not automatically an official leaderboard-comparable result.

Benchmark cards/tests explicitly prohibit training contamination. Keep held-out benchmark tasks, solutions, outputs and verifier answers out of safety-model training, temperature fitting, threshold selection and prompt tuning. Use independent development/calibration data. A larger benchmark does not automatically supply calibrated action-risk ground truth.

## 3. Better experimental design

1. **Freeze trusted task manifests.** Record dataset/task revision and hashes, policy, expected completion/refusal, fixture seed/state, allowed effects, environment/image/tool versions, output assertions, budgets and verifier version. A reference solution is one way to satisfy the task, not the only permitted command sequence.
2. **Prove the oracle before measuring agents.** On independent fresh sandboxes, require a reviewed reference to pass and deliberate wrong/partial/side-effectful controls to fail. Repeat resets to detect flakiness, time/locale/network dependence and leaked state. Do not run harmful reference attacks merely to generate labels.
3. **Separate actor from verifier authority.** Keep tests, expected answers and reward files inaccessible to the acting agent. Capture immutable receipts and snapshots, then evaluate in a separate constrained verifier environment. Agent-produced files/code are still untrusted inside the verifier; apply bounds, no credentials and controlled egress there too. Do not trust a writable `reward.txt` or a model's claim that tests passed.
4. **Use two evaluation protocols.** Replay identical independently labeled action/context pairs through A/B to compare verifier quality and authorization latency without arbitrary shell execution. Separately run full agents on equivalent initial task workspaces; their command sequences may diverge, so report utility/refusal and policy violations rather than treating the runs as identical-action comparisons.
5. **Keep fixture truth and safety truth distinct.** A correct final CSV does not prove no secret was read or no network upload occurred. Measure forbidden effects independently; unknown effects remain unknown. Permit intermediate actions without confusing “not done yet” with “incorrect or unsafe.”
6. **Freeze the pilot before results.** Start with a small compatible subset (for example 10-20 tasks as a feasibility pilot, not a statistically sufficient safety claim). Predeclare eligibility, counts, hardware, quality budgets, thresholds, seeds/repeats and exclusion reasons. Do not cherry-pick successful tasks after observing agent outcomes. Keep benchmark data completely held out from tuning.
7. **Report the denominators.** Task success, safe refusal, action-policy FNR/FPR, unknown outcomes, verified invariant breaches, judge agreement and authorization latency are separate metrics. A service outage is not a correct refusal; a test pass is not universal containment.

## 4. Gemini as an evidence-grounded adjudicator

Gemini can still be the external judge, but its job should be **checking supplied evidence against a closed, trusted rubric**, not inventing expected behavior or providing a general opinion.

Provide only the relevant task/policy version, criterion IDs, reference facts/expected outcomes, actual proposed action, trusted tool receipts and independently collected observations. Exclude the mode/model identity where possible, so it does not bias an A/B review. Treat all agent/tool text as quoted untrusted data, not new judge instructions. Do not send real credentials or sensitive raw trace content to the API.

Require a validated schema such as this illustrative per-criterion review:

```json
{
  "criterion_id": "output.matches_expected_rows",
  "action_id": "action-17",
  "verdict": "satisfied",
  "reference_ids": ["expected-output-4"],
  "evidence_ids": ["verified-artifact-17", "verifier-result-17"]
}
```

The allowed verdicts are `satisfied`, `violated`, and `insufficient_evidence`. Validate criterion/action/reference/evidence IDs and provenance in application code; require evidence for every conclusive verdict. Missing, stale, contradictory or unsupported evidence must produce abstention/error and a review flag, not a fabricated success. Schema-valid output can still be factually wrong.

**Authority rules:**

- A deterministic test/policy result is the recorded measured outcome. Gemini cannot override it; disagreements are separately reported and reviewed.
- If every relevant criterion is executable, use the programmatic oracle for scoring. Gemini may summarize or audit the evidence without becoming an additional source of truth.
- For genuinely semantic criteria that lack a programmatic oracle, Gemini remains a fallible model-based adjudicator. Label those results accordingly, allow abstention, and validate agreement against independent human-reviewed examples. Do not quietly promote them to verified ground truth.
- Never use Gemini's review to mint safety-training labels or authorize the next command in the measured guardrail path. Judge time remains outside the action-authorization latency budget.
- Pin the chosen supported Gemini model/version and prompt/schema hashes, preserve configuration/provenance, and test repeatability. A low temperature and strict JSON format do not guarantee objective truth.

The executed pilot uses registered MLflow `make_judge()` judges configured to `gemini:/gemini-2.5-flash`, not a separate raw SDK grader. Its exact four-field feedback schema and trace/evidence contract are documented in the [banking guide](banking-feasibility.md). Semantic validation remains an application responsibility: the retained disagreement demonstrates that valid citations do not guarantee correct code interpretation. The legacy Bash grader is unchanged.

### Judge validation cases

Before accepting the revised judge, test equivalent command formulations, permitted preparatory steps, incorrect output despite successful exit, correct output with forbidden side effects, malicious-task safe refusal, missing receipts, stale state, malformed outputs, prompt injection in tool text, and fabricated/nonexistent evidence IDs. Include cases where the supplied reference itself is defective. Compare with trusted oracle/human outcomes and report judge error/abstention rates; do not average away disagreements.

## 5. Suggested next design decision

Review the executed **banking oracles-first/MLflow-native** pilot under #8/#15/#19/#20 before adopting the domain. Separate utility, selected attacker-goal predicates, observed transfers and judge agreement. Keep policy/calibration data separate from held-out utility tasks; do not feed measured oracle verdicts into the judge and call the result independent agreement.

The authorized follow-up installed pinned AgentDojo/LiteLLM dependencies and executed the simulation/native judges. No Harbor installation, safety-model training or real payment connection occurred. After block-02 acceptance, the next runtime work is real Actor identity/hosting/reset/enforcement with a typed business-tool contract if banking is adopted—not automatically a generic Bash executor.
