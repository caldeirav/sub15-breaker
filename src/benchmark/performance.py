"""Matched adapter timings, never a timeout-based speedup or safety certificate."""
from collections import defaultdict
import math


def compare_reviews(classifier_records,llm_records):
    arms=[];excluded=[]
    for records in (classifier_records,llm_records):
        grouped=defaultdict(list)
        for record in records:
            if record.get("guard_control") is not None:
                excluded.append(dict(case_id=record.get("case_id"),reason="deterministic/fault control, not a learned review"));continue
            for action in record["evidence"]["actions"]:
                review=action.get("guard") or {}
                if review.get("input_digest"):grouped[review["input_digest"]].append(review)
        arms.append(grouped)
    pairs=[]
    for digest in sorted(set(arms[0])|set(arms[1])):
        left,right=arms[0][digest],arms[1][digest]
        for index in range(max(len(left),len(right))):
            values=[rows[index] if index<len(rows) else None for rows in (left,right)]
            if any(v is None or v.get("decision") not in {"allow","block"} or v.get("error") or
                    v.get("discarded_decision") is not None or type(v.get("review_latency_ns")) not in {int,float} or
                    not math.isfinite(v["review_latency_ns"]) or v["review_latency_ns"]<=0 for v in values):
                excluded.append(dict(input_digest=digest,occurrence=index,reason="missing, errored, cancelled or invalid measurement"));continue
            classifier,llm=values
            pairs.append(dict(input_digest=digest,occurrence=index,classifier_review_ms=classifier["review_latency_ns"]/1e6,
                llm_review_ms=llm["review_latency_ns"]/1e6,llm_over_classifier_ratio=llm["review_latency_ns"]/classifier["review_latency_ns"],
                decisions_agree=classifier["decision"]==llm["decision"]))
    return dict(scope="same serialized input; completed adapter reviews only; occurrence pairing, no preferred-outcome selection",
        status="paired_samples_available" if pairs else "insufficient_completed_pairs",pairs=pairs,excluded=excluded,
        safety_equivalence_claim=False,complete_admission_latency_claim=False,sub15ms_demonstrated=False,
        note="No timing threshold certified here. Separate startup/cold/warm/device/length and reviewer quality before drawing conclusions.")


def case_comparisons(plan,records):
    """Keep scripted canaries and each real card group separate."""
    groups={}
    specs={case["case_id"]:case for case in plan["cases"]}
    for record in records:
        spec=specs[record["case_id"]]
        if spec.get("arm") not in {"classifier","llm"}:continue
        group="scripted_canary" if spec["kind"]=="canary" else spec.get("card_id")
        if group is None:continue
        groups.setdefault(group,dict(classifier=[],llm=[]))[spec["arm"]].append(record)
    return {group:compare_reviews(arms["classifier"],arms["llm"]) for group,arms in groups.items()}
