from copy import deepcopy

import pytest

from src.benchmark.golden_report import assess,without_thresholds,render


def paired():
    sources=[dict(candidate_id=name,task_id="user_task_0",unsafe_label=int(name=="extra"),input_digest=name,cohort="golden",label_source="CODE/frozen",use_cases=groups)
        for name,groups in (("read",["D01","D02"]),("pay",["D01","D02"]),("extra",["D02"]),("profile-read",["D03"]),("profile",["D03"]))]
    cases=[dict(kind="accuracy",case_id="case-"+r["candidate_id"]) for r in sources]
    rows=[dict(case_id=c["case_id"],candidate_id=s["candidate_id"],cohort=s["cohort"],unsafe_label=s["unsafe_label"],input_digest=s["input_digest"],backend=arm,
        review=dict(decision="block" if s["unsafe_label"] else "allow",error=None)) for c,s in zip(cases,sources) for arm in ("classifier","llm")]
    return dict(cases=cases,accuracy=dict(rows=sources)),rows


def test_golden_case_accuracy_is_explicit_not_latency_or_fault_success():
    plan,rows=paired();value=assess(rows,plan)
    assert value["unique_inputs"]==5
    for arm in ("classifier","llm"):
        assert value["overall"][arm]["accuracy_errors_in_denominator"]==1
        assert value["by_use_case"]["D01"][arm]["total"]==2
        assert value["by_use_case"]["D02"][arm]["total"]==3
        assert value["by_use_case"]["D03"][arm]["total"]==2
    assert "D04" not in value["by_use_case"] and value["results"][2]["golden"]=="block"


def test_wrong_and_error_golden_verdicts_stay_in_accuracy_denominator():
    plan,rows=paired();rows[0]["review"]=dict(decision="block");rows[1]["review"]=dict(decision="error",error="timeout")
    value=assess(rows,plan)
    assert value["overall"]["classifier"]["confusion"]["false_block"]==1
    assert value["overall"]["llm"]["errors"]==1 and value["overall"]["llm"]["total"]==5
    assert not value["results"][0]["backends"]["llm"]["correct"]
    with pytest.raises(ValueError):assess(rows[:-1],plan)


def test_new_report_focuses_accuracy_and_keeps_source_hashes_without_threshold_counts():
    plan,rows=paired();report=dict(namespace="nd11",qualified=True,golden_accuracy=assess(rows,plan),service_startup={},cards=[],external_harness_verdict="supported",
        native_core_below15=10,decision_core=dict(read=dict(below15=6,core=dict(median_ms=12))),source_hashes={"/Code/sub15-breaker/source.json":"a"*64})
    value=without_thresholds(report);assert value["source_hashes"]==report["source_hashes"] and "native_core_below15" not in value
    text=render(value)
    assert "100.0%" in text and "Golden verdict" in text and "False allows" in text
    assert "below15" not in text and "startup" in text.lower()
