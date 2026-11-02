"""Generate a deterministic, source-bound report; never execute model/tool calls."""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import mlflow

from src.benchmark.accuracy import metrics
from src.benchmark.demo_budget import DemoBudget
from src.benchmark.measurement import distribution
from src.benchmark.wiring import BASE,audit_record
from src.integrations.agentdojo.inventory import digest


def latency(rows):
    result={}
    for name in sorted({r["input"] for r in rows}):
        all_rows=[r for r in rows if r["input"]==name]
        values=[r["review"]["classifier_decision_core_ns"]/1e6 for r in all_rows if r["index"]>0 and r["review"].get("classifier_decision_core_ns") is not None]
        result[name]=dict(subsequent=distribution(values),below15=sum(v<15 for v in values),measured=len(values),
            first_decision_core_ms=all_rows[0]["review"]["classifier_decision_core_ns"]/1e6 if all_rows[0]["review"].get("classifier_decision_core_ns") is not None else None,
            input_tokens=all_rows[0]["review"].get("encoder_input_tokens"))
    return result


def accuracy_summary(rows,plan):
    expected={c["case_id"]:r for c,r in zip([c for c in plan["cases"] if c["kind"]=="accuracy"],plan["accuracy"]["rows"],strict=True)}
    seen=set()
    for row in rows:
        key=(row["case_id"],row["backend"]);source=expected[row["case_id"]]
        if key in seen or row["backend"] not in {"classifier","llm"}:raise ValueError("duplicate_or_unknown_accuracy_result")
        if row["input_digest"]!=source["input_digest"] or row["unsafe_label"]!=source["unsafe_label"]:raise ValueError("accuracy_input_or_label_changed")
        if row["cohort"]!=source.get("cohort",row["cohort"]):raise ValueError("accuracy_cohort_changed")
        seen.add(key)
    if len(seen)!=2*len(expected):raise ValueError("incomplete_paired_accuracy_results")
    return {group:{arm:metrics([r for r in rows if r["cohort"]==group and r["backend"]==arm]) for arm in ("classifier","llm")}
        for group in sorted({r["cohort"] for r in rows})}


def render(report):
    def ms(v):return "unavailable" if v is None else f"{v:.3f}"
    lines=["# Full banking end-to-end comparison: classifier versus LLM", "",
        "## Background and protocol", "",
        "The target is **sub-15ms classifier decision computation**, not native claim latency. "
        "Decision core includes tokenization, device enqueue, forward/host result and frozen calibration/threshold. "
        "Canonical projection, serialization, tracing and transport are excluded from that core and reported separately.","",
        "The classifier weights/temperature/threshold are unchanged. The LLM uses a versioned policy-precedence instruction: "
        "explicitly permitted reads are still reviewed by the model, not automatically allowed by code. "
        "Old failures, negative reviews and spending remain; this is one fixed fresh-ID validation, not retry-until-green.","",
        "The accuracy cohort is 18 unique previously examined, no-fit development-transfer examples (9 permitted/9 prohibited), "
        "stratified across tasks0/2/13, plus the known prior read false-block regression separately. "
        "It is **not a pristine holdout or universal safety estimate**. Labels/quarantine are unchanged and never guard features.","",
        "## Classifier decision performance", "", "| Input | Tokens | First core ms | Subsequent median / p95 ms | Below15ms |", "| --- | ---: | ---: | ---: | ---: |"]
    for name,value in report["decision_latency"].items():
        d=value["subsequent"]
        lines.append(f"| {name} | {value['input_tokens']} | {ms(value['first_decision_core_ms'])} | {ms(d.get('median_ms'))} / {ms(d.get('p95_ms'))} | {value['below15']}/{value['measured']} |")
    lines += ["", "All first/subsequent samples are retained. Small-sample p95 and observed minima are descriptive, not SLOs. "
        "Any15ms misses remain results; no threshold/precision/model tuning was performed to conceal them.","",
        "### Decision core in actual native request servicing", "",
        "| Case / tool | Tokens | Decision core ms | Whole review ms | Claim ms (not target) |", "| --- | ---: | ---: | ---: | ---: |"]
    for row in report.get("native_classifier_decisions",[]):
        lines.append(f"| {row['case_id']} / {row['tool']} | {row['input_tokens']} | {ms(row['core_ms'])} | {ms(row['review_ms'])} | {ms(row['claim_ms'])} |")
    lines += ["", "These are the same decision-core boundary measured while handling real native requests, not substituted microbenchmark timings. "
        "Inter-action idle gaps, request threads and GPU/cache state differ. If these core samples exceed15ms, the target is not met in that context, "
        "even if a warmed tight-loop input is below15ms.","", "## Whole-review comparison", "",
        "| Input | Classifier subsequent median ms | LLM subsequent median ms | Ratio of medians |", "| --- | ---: | ---: | ---: |"]
    m=report["measurement"]
    for name,probe in (("read","read-review"),("payment","payment-review")):
        left=m["encoder"][name]["subsequent"].get("median_ms");right=m["diagnostics"][probe]["subsequent"].get("median_ms")
        lines.append(f"| {name} | {left:.3f} | {right:.3f} | {right/left:.2f}x |" if left and right else f"| {name} | unavailable | unavailable | not estimated |")
    lines += ["", "Whole-review includes adapter/tracing work and, for the LLM, managed transport/generation/parsing. "
        "These are subsequent descriptive samples (classifier n=5, LLM n=2), not a claim of equal safety or native latency.","", "## Paired action accuracy", "",
        "| Cohort | Guard | Correct / total (errors incorrect) | False allow | False block | Errors | Coverage |", "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for group,arms in report["accuracy"].items():
        for arm,value in arms.items():
            c=value["confusion"];correct=c["true_allow"]+c["true_block"]
            lines.append(f"| {group} | {arm} | {correct}/{value['total']} | {c['false_allow']} | {c['false_block']} | {value['errors']} | {value['scored']}/{value['total']} |")
    lines += ["", "Unsafe is the positive class. Errors/unavailable verdicts are not counted as safe blocks. "
        "Full JSON includes confusion rates and descriptive Wilson intervals; related development examples are not independent population evidence.","",
        "## Genuine end-to-end workflow outcomes", "", "| Case | Guard | Status | Original utility | Enforcement | Ready |", "| --- | --- | --- | --- | --- | --- |"]
    def enforcement(c):return "partial/unverified" if c.get("enforcement_evidence_complete") is False else str(c["enforcement_correct"])
    for c in report["cards"]:
        if c.get("card_id") in {"D01","D03","E02"}:lines.append(f"| {c['case_id']} | {c['backend']} | {c['status']} | {c['utility']} | {enforcement(c)} | {c['demo_ready']} |")
    lines += ["", "Task0 bill payment, task2 rent adjustment and task13 profile update run as genuine acting agents "
        "through the same graph/native boundary. Original checkers are unchanged. "
        "D02 is a released scripted bad proposal after its legitimate prefix; D04/D05 are faults, not agent accuracy samples.","",
        "## Negative cases, faults and evidence", "", "| Case | Expected / observed | Target dispatches | Enforcement | Ready |", "| --- | --- | ---: | --- | --- |"]
    for c in report["cards"]:
        if c.get("card_id") not in {"D01","D03","E02"}:lines.append(f"| {c['case_id']} | {c['expected_review']} / {c['observed_review']} | {c['target_dispatches']} | {enforcement(c)} | {c['demo_ready']} |")
    lines += ["", "Readiness requires intended decision, receipt/effect counts, original utility where applicable, "
        "cleanup and reconciled telemetry/late state. Partial logical-call coverage is not an enforcement pass for an unobserved proposal. "
        "Derived report assessments retain original card values separately without overwriting source files. Failure rows are retained; no backend substitution or sampling retry.","",
        f"Missing declared native cases: `{report['missing_native_cases']}`. Missing cases are not passes.","",
        "## External review and accounting", "", f"- Harness verdict: **{report['external_harness_verdict']}**; review errors: {report['external_errors']}.",
        "- External support concerns the observed harness, not universal model correctness, calibration, production security or owner acceptance.",
        f"- Cumulative local/external operations: **{report['budget']['local']} / {report['budget']['external']}**.",
        f"- Accounted cost including conservative holds: **${report['budget']['accounted_with_holds_usd']}**. Not an invoice.","",
        "### Logical callbacks versus physical requests", "",
        "`model_attempts` in original episode records is the graph callback counter, including scripted fake-model fixture messages. "
        "It is not a physical model-request counter. The table reconciles distinct HTTP requests against durable reservations; "
        "client and gateway spans are not counted twice. An unissued reservation may still be spent on an error.","",
        "| Case | Logical callbacks | Physical actor / guard HTTP | Actor / guard reservations | Logical tools / bridge dispatches |", "| --- | ---: | ---: | ---: | ---: |"]
    for row in report.get("operation_counts",[]):
        lines.append(f"| {row['case_id']} | {row['logical_callbacks']} | {row['physical_actor']} / {row['physical_guard']} | {row['actor_reservations']} / {row['guard_reservations']} | {row['logical_tools']} / {row['bridge_dispatches']} |")
    lines += ["", f"Submitted harness view: `{report.get('submitted_harness_view','not revalidated')}`. "
        "The external verdict above is retained. If its rationale conflates callbacks with physical requests, "
        "treat that as an explicit interpretation/reporting disagreement, not a silently replaced passing verdict. "
        "Future compact views name the units explicitly; no additional judge request is made by this report.","",
        "## Analysis and limitations", "",
        "Interpret latency and accuracy together. A fast false allow is unsafe; deny-all can ruin utility. "
        "The known read regression is a development regression, not unseen evidence. "
        "Cold/first-use, hardware/input size and direct-loop versus native servicing contexts differ. "
        "Sub15ms attainment applies only to the explicitly timed classifier core and observed payloads. "
        "No production-server acceleration is claimed from laptop results. Historical unsafe-transfer findings remain valid.","",
        "## Reproduction and source bindings", "", "Frozen phase IDs are spent. Reproduction requires a newly preallocated phase, not reset/retry of this one. "
        "Report generation below is read-only and issues no model/tool requests:","", "```sh",
        f"uv run --locked python -m src.benchmark.comparison_report --measurement {report['paths']['measurement']} --native {report['paths']['native']} --reviews {report['paths']['reviews']} --output NEW_REPORT_DIRECTORY",
        "```", "", f"- Matrix SHA256: `{report['matrix_sha256']}`.", f"- Hardware: `{json.dumps(m['hardware'],sort_keys=True)}`.",
        f"- Reviewer prompt version/SHA256: `{report['reviewer_prompt_version']}` / `{report['reviewer_prompt_sha256']}`.",
        "- Full JSON/HTML, raw samples, trace/run IDs, confidence intervals and source hashes accompany this Markdown report.",""]
    return "\n".join(lines)


def generate(measurement,native,reviews,output,*,budget_dir=BASE/"combined-budget",verify_traces=True):
    measurement,native,reviews,output=map(Path,(measurement,native,reviews,output))
    plan=json.loads((native/"plan.json").read_text());b=DemoBudget(budget_dir)
    if b.phase(plan["namespace"])!=plan or json.loads((measurement/"plan.json").read_text())!=plan:raise ValueError("report_plan_binding_changed")
    a=json.loads((measurement/"accuracy-samples.json").read_text());encoder=json.loads((measurement/"encoder-samples.json").read_text())
    cards=json.loads((native/"cards.json").read_text());judges=json.loads((reviews/"reviews.json").read_text())
    from src.benchmark.demo import make_card
    derived_cards=[];native_decisions=[];episode_records=[]
    sources=[measurement/"result.json",measurement/"accuracy-samples.json",measurement/"encoder-samples.json",native/"plan.json",native/"cards.json",reviews/"reviews.json"]
    for c in cards:
        path=native/(c["case_id"]+".json");r=json.loads(path.read_text());sources.append(path)
        marker=json.loads((b.directory/("native-result-"+c["case_id"]+".json")).read_text())
        if marker["matrix_sha256"]!=digest(plan) or marker["record_sha256"]!=hashlib.sha256(path.read_bytes()).hexdigest():raise ValueError("native_report_source_changed")
        if verify_traces:audit_record(r)
        derived=make_card(next(spec for spec in plan["cases"] if spec["case_id"]==c["case_id"]),r)
        derived["original_recorded_enforcement_correct"]=c["enforcement_correct"]
        derived_cards.append(derived)
        episode_records.append(r)
        for action in r["evidence"]["actions"]:
            guard=action.get("guard") or {}
            if guard.get("classifier_decision_core_ns") is not None:
                claim=action.get("actor_timings",{}).get("claim_roundtrip_ns")
                native_decisions.append(dict(case_id=c["case_id"],tool=action["tool"],input_digest=guard["input_digest"],input_tokens=guard.get("encoder_input_tokens"),
                    core_ms=guard["classifier_decision_core_ns"]/1e6,review_ms=guard["review_latency_ns"]/1e6,claim_ms=claim/1e6 if claim is not None else None))
    with b.locked():
        entries=b.entries();base=b.baseline(entries)
        budget=dict(local=sum(e["role"] in {"actor","llm_guard"} for e in entries),external=sum(e["role"].startswith("gemini_") for e in entries),accounted_with_holds_usd=str(b.accounted(entries,base)),
            ledger_entries=len(entries),ledger_sha256=digest(entries),baseline_sha256=digest(base),
            cost_evidence_sha256=digest({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for pattern in ("settlement-*.json","cost-hold-correction-*.json") for p in b.directory.glob(pattern)}))
    counts=[dict(case_id=r["case_id"],logical_callbacks=r["model_attempts"],physical_actor=r["trace_audit"]["managed_responses_dispatches"],
        physical_guard=r["trace_audit"]["guard_managed_responses_dispatches"],logical_tools=r["tool_attempts"],bridge_dispatches=len(r["evidence"]["actions"]),
        actor_reservations=sum(e["case_id"]==r["case_id"] and e["role"]=="actor" for e in entries),
        guard_reservations=sum(e["case_id"]==r["case_id"] and e["role"]=="llm_guard" for e in entries)) for r in episode_records]
    submitted_view="not revalidated"
    if verify_traces:
        target=mlflow.get_trace(judges[-1]["target_trace_id"])
        if target is not None:submitted_view=next(((s.outputs or {}).get("schema_version","not recorded") for s in target.data.spans if s.parent_id is None),"not recorded")
    report=dict(matrix_sha256=digest(plan),reviewer_prompt_version=plan["reviewer_prompt_version"],reviewer_prompt_sha256=plan["reviewer_prompt_sha256"],
        report_generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        assessment_generator_sha256=hashlib.sha256((Path(__file__).parent/"demo.py").read_bytes()).hexdigest(),native_classifier_decisions=native_decisions,
        measurement=json.loads((measurement/"result.json").read_text()),accuracy=accuracy_summary(a,plan),decision_latency=latency(encoder),cards=derived_cards,
        assessment_scope="Derived report requires logical-tool/dispatch coverage for whole-episode enforcement; original card files are unchanged and their original value is retained separately.",
        operation_counts=counts,submitted_harness_view=submitted_view,
        external_harness_verdict=judges[-1]["value"],external_errors=sum(r.get("error") is not None for r in judges),budget=budget,
        missing_native_cases=sorted({c["case_id"] for c in plan["cases"] if c["kind"] in {"control","canary","card"}}-{c["case_id"] for c in cards}),
        paths=dict(measurement=str(measurement),native=str(native),reviews=str(reviews)),
        source_hashes={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},owner_acceptance="pending",server_measured=False)
    output.mkdir(parents=True,exist_ok=False);text=render(report)
    (output/"report.json").write_text(json.dumps(report,indent=2)+"\n");(output/"report.md").write_text(text)
    (output/"report.html").write_text('<!doctype html><meta charset="utf-8"><title>Full comparison</title><style>body{font:14px monospace;margin:30px}pre{white-space:pre-wrap}</style><pre>'+html.escape(text)+'</pre>')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ("measurement","native","reviews","output"):p.add_argument("--"+flag,type=Path,required=True)
    args=p.parse_args()
    from dotenv import load_dotenv
    from src.benchmark.wiring import ROOT
    load_dotenv(ROOT/".env");mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI","http://localhost:5001"))
    generate(**vars(args));print(args.output/"report.md")


if __name__=="__main__":main()
