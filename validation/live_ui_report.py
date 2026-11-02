"""Render a versioned report from completed browser evidence and final readback only."""
import argparse
import hashlib
import json
from pathlib import Path


def render(browser, final):
    browser=Path(browser)
    proof=json.loads((browser/"proof.json").read_text())
    results=json.loads((browser/"results.json").read_text())
    if proof.get("mode")!="live" or not proof.get("passed"):
        raise ValueError("actual_live_browser_proof_required")
    if (hashlib.sha256((browser/"proof.json").read_bytes()).hexdigest()!=final["browser_proof_sha256"] or
        hashlib.sha256((browser/"results.json").read_bytes()).hexdigest()!=final["browser_results_sha256"]):
        raise ValueError("browser_evidence_hash_binding_changed")
    if proof["runIds"]!=[r["id"] for r in results]:raise ValueError("browser_run_identity_binding_changed")
    if [r["card"] for r in results]!=["D01","D02","D03","D04","D05"]:
        raise ValueError("exact_five_card_matrix_required")
    if not all(r["phase"]=="completed" for r in results):raise ValueError("incomplete_runs_need_an_explicit_failure_report")
    if not final.get("preservation_verified") or not final.get("resources_restored") or not final.get("no_actors_remaining"):
        raise ValueError("final_preservation_restoration_and_cleanup_proof_required")
    campaign=final["campaign"]
    if campaign!="ui1":raise ValueError("this_versioned_renderer_is_bound_to_ui1")
    lines=[f"# Live demo UI results — {campaign}","",
        f"Version: **live-demo-ui-sequential-v1**. Executed **{final['date']}**, runtime source `{final['runtime_source']}`.",
        "[Demo/UI operator guide](../demo.md#live-web-interface--end-to-end) · [Validation methods](../validation.md) · [Model/calibration](../model.md)","",
        "## Scope and outcome","",
        "Five explicit browser Run clicks, ten fresh lanes, one shared Qwen server. Arms were displayed side by side but executed sequentially in the frozen order. Six native controls and two full-prefix real canaries preceded the cards (18 native cases total). D01/D03 are genuine agents, D02 a released scripted extra-proposal control, D04/D05 injected faults—not model accuracy samples.","",
        "| Card | Frozen order | Classifier-route golden outcome | LLM-route golden outcome | Gemini harness |",
        "| --- | --- | --- | --- | --- |"]
    for r in results:
        def outcome(arm):
            s=r["lanes"][arm]["summary"]
            return f"{'PASS' if s['golden_pass'] else 'FAIL'}; expected {s['expected']}, observed {s['observed']}"
        lines.append(f"| {r['card']} | {' → '.join(r['order'])} | {outcome('classifier')} | {outcome('llm')} | {r['external_review']['verdict']} |")
    lines += ["", "Golden means the original pinned utility plus declared target execution/receipt/state invariants. It is not an empirical claim of general safety. A correctly recorded model mistake remains a failed golden outcome even if the harness review is supported. Scripted negative and fault cases are not acting-agent attack-win rates or extra classifier accuracy points.","",
        "## Guardrail performance after readiness","",
        "Medians in milliseconds with exact action-review counts. Startup/priming and Gemini are excluded; all raw observations remain in the source artifacts. Completed allow/block reviews are the speed samples; errors/unknowns remain separately visible. Different trajectories and unmatched action inputs do not establish an isolated same-input speedup.","",
        "| Card | Classifier core median ms / n | Classifier whole-review median ms / n | LLM whole-review median ms / n |",
        "| --- | ---: | ---: | ---: |"]
    def value(v):return f"{v['median_ms']:.3f} / {v['count']}" if v else "N/A"
    for r in results:
        c=r["lanes"]["classifier"]["summary"];l=r["lanes"]["llm"]["summary"]
        lines.append(f"| {r['card']} | {value(c['timing']['classifier_core'])} | {value(c['timing']['guard_whole_review'])} | {value(l['timing']['guard_whole_review'])} |")
    lines += ["", "Classifier core includes tokenization, device enqueue, forward/host result and frozen calibration/threshold. Whole review includes adapter/tracing and, for LLM, network/generation/parsing. Compare whole-review columns at the same boundary; core is a subset. Fault model timers are N/A, not zero.15ms is the classifier-computation target, not native claim latency; no attainment counts or uniform-latency claim are made.","",
        "Measured classifier core ranges: "+"; ".join(f"{card} {min(values):.3f}–{max(values):.3f}ms" for card,values in final["measured_classifier_core_raw_ms"].items())+". The slow D02 sample is AFTER readiness and remains measured—not discarded or reclassified as startup. Priming establishes functional readiness, not GPU-clock/idle/payload latency guarantees; the unique cause of variability is not established.","",
        "## Component breakdown","",
        "Each cell is median ms / n. These are nested/inclusive boundaries, **not additive layers**. Gateway server spans include backend time, not a fabricated pure gateway/queue cost. Host event journaling and tracing overhead are real. Full timing/source fields, including fault mechanics, remain in the JSON and live panels.","",
        "| Card | Boundary | Classifier route | LLM route |","| --- | --- | ---: | ---: |"]
    boundaries=[("acting_model_http","Acting-model HTTP, including gateway/provider"),
        ("gateway_model_server","Gateway model spans, including provider"),("gateway_mcp_server","Gateway MCP spans, including tool backend"),
        ("snapshot_prepare","Snapshot/ticket prepare"),("context_projection","Context projection"),
        ("native_claim_roundtrip","Native claim, including guard"),("tool_compute","Actor computation"),
        ("commit_roundtrip","State/receipt commit"),("mcp_tool_roundtrip","MCP inclusive roundtrip")]
    for r in results[:3]:
        for key,label in boundaries:
            lines.append(f"| {r['card']} | {label} | {value(r['lanes']['classifier']['summary']['timing'].get(key))} | {value(r['lanes']['llm']['summary']['timing'].get(key))} |")
    lines += ["", "## Startup and external review are separate","",
        "The first explicit Run performed a real gVisor identity/readiness check without a trial/tool effect, two reserved functional actor/reviewer model probes, and two fixed unlabelled classifier priming passes on the measured resident worker. Priming never gated on a preferred verdict or speed. No shared-Qwen reload, precision/threshold/weight change, hidden warmup, model/action retry or response repair.","",
        f"Recorded classifier priming forwards: **{final['priming_forwards']}**. Startup model requests: **{final['startup_model_requests']}**. Startup costs are retained in `services-startup.json`, not included in the measured tables.","",
        f"Startup-only: classifier loading **{final['startup_metrics']['load_ms']:.3f}ms**, first initialization core **{final['startup_metrics']['first_priming_core_ms']:.3f}ms**, total readiness/probe/priming gate **{final['startup_metrics']['elapsed_ms']:.3f}ms**. These are separate costs, not free startup or measured request latency.","",
        "Gemini ran after each pair, outside decision latency: four task-criterion reviews per genuine episode and one scoped harness review per pair; scripted/fault applicability was explicit in `live-native-card-review-v1`. Negative/error/insufficient-evidence outcomes remain unchanged. This is runtime/evidence review, not a visual-layout audit, independent safety labels or human acceptance.","",
        "## Budget, preservation and browser verification","",
        f"Frozen maxima:63 local /21 external requests,18 trials,192 action slots and1200 evidence slots. Actual campaign: **{final['campaign_local']} local /{final['campaign_external']} external**. Cumulative: **{final['accounting']['local']} local /{final['accounting']['external']} external /${final['accounting']['accounted_with_holds_usd']} including conservative holds**. Globals2048/512/$100 unchanged; holds are not an invoice and unused capacity is not authorization.","",
        "All old state/action/receipt/outbox history and the same key/PVC were verified unchanged, excluding only this new campaign's rows. Prior reservation used counts remain retained after release. Final readback verified no Actors remain and original native hook/model/MCP route specifications/metadata were restored. No spent IDs or allocations were reset.","",
        "Actual Chromium verified five explicit Run POSTs, no dispatch on loading/selecting/reloading, sequential lane observations with complete event sequences, all five card panels, desktop/mobile layout, keyboard access and no JavaScript errors. Offline fixture tests were labelled as fixtures and are not this live evidence.","",
        "## Versioned evidence","",
        f"- Frozen allocation SHA256: `{final['allocation_sha256']}`.",
        f"- Campaign MLflow run: `{final['parent_run_id']}` in `breaker-banking-target-agent` (experiment5, owner-local tracking).",
        "- Sanitized publication bundle: `live/ui1-publication-v1/` in that run, with source/published SHA256 manifest; credentials, kubeconfigs and raw infrastructure configurations are excluded.",
        "- Before live calls:726 tests passed on Python3.11–3.13 and PR CI was green. Real Chromium fixture testing was separate from this live campaign.",
        f"- Actor/store image: `{final['image']}`.",
        "- Hardware/profile: Apple M4 Max /48GiB, macOS/arm64; PyTorch MPS resident ModernBERT v1, frozen calibration/threshold; Qwen3-30B-A3B-Instruct-2507 MLX4-bit/context8192; managed Responses/MCP and native-measure-v2. No model/precision/threshold retuning or shared-model reload.",
        "- Browser proof/screenshots/results/events: `.infra/benchmark-guard-harness/ui1-browser-live/`.",
        "- Final source/preservation/restoration/ledger proof: `.infra/benchmark-guard-harness/ui1-final-proof.json`.",
        "- Source records/startup/controls: `.infra/live-demo-ui/ui1/runtime/`; per-job records/reviews/events: `.infra/live-demo-ui/ui1/RUN_ID/`.",
        "- Local UI auth capability is separate from provider/platform credentials. The live API is localhost-only; no models are invoked by opening/reading its results.",
        "- Previous [nd11/nd12 report](https://github.com/caldeirav/sub15-breaker/blob/80f4206/docs/results/demo-nd11-nd12.md) remains in Git history with its original raw evidence; it is not this live UI campaign.","",
        "| Card | UI run ID | Classifier MLflow run / trace | LLM MLflow run / trace |","| --- | --- | --- | --- |"]
    for r in results:
        c=r["lanes"]["classifier"]["summary"];l=r["lanes"]["llm"]["summary"]
        lines.append(f"| {r['card']} | `{r['id']}` | `{c['run_id']}` / `{c['trace_id']}` | `{l['run_id']}` / `{l['trace_id']}` |")
    lines += ["", "## Limits and next use","",
        "This campaign's slots are spent. A new presentation needs a separately approved frozen `uiN` allocation; do not reset/rerun ui1. The source UI and end-to-end prerequisites are in the demo guide. Earlier demo reports remain in Git history/raw artifacts, not relabelled by this test.","",
        "Curated golden success is not larger held-out accuracy (#56), resolution of the rent false block (#55), full admission/load-tail qualification (#11), native serving optimization (#13), completed soak (#39), turnkey artifact distribution/SBOM (#10) or final owner acceptance (#17). Historical v2 transfer failure, negative reviews and failed earlier runs remain unchanged.",""]
    return "\n".join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--browser",type=Path,required=True);p.add_argument("--final-proof",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise ValueError("new_output_file_required")
    text=render(args.browser,json.loads(args.final_proof.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(text);print(args.output)


if __name__=="__main__":main()
