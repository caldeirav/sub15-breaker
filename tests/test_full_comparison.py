import json
from contextlib import nullcontext
from types import SimpleNamespace as S

import pytest
from langchain_core.messages import AIMessage

from src.benchmark.accuracy import cohort,metrics,review_input
from src.benchmark.comparison_report import accuracy_summary,latency,render
from src.benchmark.guards import Calibration,ClassifierGuard,LLMGuard,ReviewInput,timed_review
from src.integrations.agentdojo.inventory import digest


def test_v2_read_policy_is_an_instruction_not_a_code_allow_bypass():
    calls=[]
    class Model:
        def invoke(self,messages):calls.append(messages);return AIMessage(content='{"allow": false}')
    guard=LLMGuard(Model(),guard_id="v2",reserve_model=lambda:None,prompt_version="v2")
    result=guard.review(ReviewInput("pay bill","policy","Granted read tools are permitted.","get_balance",{}))
    assert result.decision=="block" and len(calls)==1
    assert "explicitly permits" in calls[0][0].content
    with pytest.raises(ValueError,match="unknown_reviewer_prompt"):LLMGuard(Model(),guard_id="x",reserve_model=lambda:None,prompt_version="unknown")


def test_decision_core_includes_frozen_calibration_without_tracing_or_second_forward():
    calls=[]
    guard=ClassifierGuard(lambda text:calls.append(text) or -1,Calibration("model","policy","cal",1,.5),model_id="model")
    guard.stage_timings_ns=dict(encoder_total_ns=100)
    result=guard.review(ReviewInput("goal","policy","policy","read",{}))
    assert result.decision=="allow" and len(calls)==1
    assert guard.decision_core_ns==100+guard.calibration_threshold_ns


def test_accuracy_errors_are_not_true_negatives_or_safe_blocks():
    rows=[dict(unsafe_label=0,review=dict(decision="allow")),dict(unsafe_label=0,review=dict(decision="block")),
        dict(unsafe_label=1,review=dict(decision="allow")),dict(unsafe_label=1,review=dict(decision="block")),
        dict(unsafe_label=1,review=dict(decision="error",error="timeout"))]
    value=metrics(rows)
    assert value["confusion"]==dict(true_block=1,true_allow=1,false_block=1,false_allow=1)
    assert value["accuracy_errors_in_denominator"]==.4 and value["conditional_accuracy"]==.5
    assert value["coverage"]==.8 and value["errors"]==1
    with pytest.raises(ValueError,match="unreviewed"):metrics([dict(unsafe_label=None,review=dict(decision="block"))])


def source_files(base):
    source=base/"modernbert-initial-validation";source.mkdir()
    rows=[]
    for task in ("user_task_0","user_task_2","user_task_13"):
        for label in (0,1):
            for i in range(3):
                value=ReviewInput(f"request-{task}-{label}-{i}","p","policy","read",{})
                rows.append(dict(candidate_id=f"{task}/{label}/{i}",task_id=task,unsafe_label=label,action_safety_label="permitted" if not label else "prohibited",
                    projection_supported=True,rule_review_status="approved_with_quarantine",model_input=value.serialized(),input_digest=value.digest(),label_source="CODE",review_sha256="review"))
    (source/"rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    coverage=dict(dataset_sha256=digest(rows));fit_manifest=dict(dataset_sha256=digest([]))
    (source/"coverage.json").write_text(json.dumps(coverage))
    (base/"modernbert-training-v1").mkdir();(base/"modernbert-training-v1/training-protocol.json").write_text(json.dumps(dict(partitions=dict(train=[],calibration=[],validation=[]),source_original_sha256=digest(coverage),source_hybrid_sha256=digest(fit_manifest))))
    (base/"hybrid-generation-v1").mkdir();(base/"hybrid-generation-v1/rows.jsonl").write_text("");(base/"hybrid-generation-v1/report.json").write_text(json.dumps(fit_manifest))
    old=base/"native-demo-5917724863ad4277b42b4c47f4505328";old.mkdir()
    value=ReviewInput("known failure","p","policy","get_balance",{})
    (old/"nd3-pay-bill-llm.json").write_text(json.dumps(dict(trace_id="old",evidence=dict(actions=[dict(tool="get_balance",guard=dict(span_id="span",input_digest=value.digest()))]),
        trace_audit=dict(span_manifest=[dict(span_id="span",inputs=dict(review=value.serialized()))]))))
    return rows


def test_fixed_cohort_is_balanced_unique_and_preserves_known_regression_separately(tmp_path):
    source_files(tmp_path);a=cohort(tmp_path);b=cohort(tmp_path)
    assert a==b and len(a["rows"])==19 and len({r["input_digest"] for r in a["rows"]})==19
    original=[r for r in a["rows"] if r["cohort"]!="known-failure-regression"]
    assert sum(r["unsafe_label"] for r in original)==9 and a["fresh_holdout"] is False
    assert a["rows"][-1]["unsafe_label"]==0 and a["rows"][-1]["cohort"]=="known-failure-regression"
    assert all(review_input(r["model_input"]).digest()==r["input_digest"] for r in a["rows"])


def test_fit_partition_overlap_cannot_be_scored_as_no_fit_transfer(tmp_path):
    rows=source_files(tmp_path)
    path=tmp_path/"modernbert-training-v1/training-protocol.json";protocol=json.loads(path.read_text());protocol["partitions"]["train"]=[rows[0]["candidate_id"]];path.write_text(json.dumps(protocol))
    with pytest.raises(ValueError,match="fit_overlap"):cohort(tmp_path)


def test_report_rejects_missing_duplicate_or_changed_paired_inputs():
    source=dict(input_digest="digest",unsafe_label=0)
    plan=dict(cases=[dict(case_id="nd4-accuracy-00",kind="accuracy")],accuracy=dict(rows=[source]))
    row=dict(case_id="nd4-accuracy-00",backend="classifier",cohort="regression",input_digest="digest",unsafe_label=0,review=dict(decision="allow"))
    with pytest.raises(ValueError,match="incomplete"):accuracy_summary([row],plan)
    other=dict(row,backend="llm");assert accuracy_summary([row,other],plan)["regression"]["llm"]["coverage"]==1
    with pytest.raises(ValueError,match="duplicate"):accuracy_summary([row,other,row],plan)
    with pytest.raises(ValueError,match="changed"):accuracy_summary([row,dict(other,input_digest="different")],plan)


def test_15ms_target_counts_actual_decision_core_not_adapter_or_claim():
    rows=[dict(input="read",index=0,review=dict(classifier_decision_core_ns=100000000,encoder_input_tokens=200)),
        dict(input="read",index=1,review=dict(classifier_decision_core_ns=14000000,review_latency_ns=50000000)),
        dict(input="read",index=2,review=dict(classifier_decision_core_ns=16000000,review_latency_ns=55000000))]
    value=latency(rows)["read"]
    assert value["below15"]==1 and value["measured"]==2 and value["subsequent"]["median_ms"]==15


def test_actor_store_readiness_authenticates_identity_without_claiming_or_tools():
    from src.banking_service.app import ActorApplication,StoreApplication
    called=[]
    identities=S(actor=lambda auth:S(name="actor",uid="uid"),driver=lambda auth:called.append("driver"))
    store=StoreApplication(S(ticket_lifetime=900),identities)
    ready=store("/actor-readiness",{},"actor token")
    actor=ActorApplication(S(call=lambda path,body:store(path,body,"actor token")),identities)
    assert actor("/admission-readiness",{},"driver token")==ready==dict(actor_id="actor",actor_uid="uid",ticket_lifetime_seconds=900)
    assert called==["driver"]


def test_generated_report_declares_boundaries_coverage_and_spent_id_rules():
    dist=dict(count=2,median_ms=12,p95_ms=14)
    accuracy=metrics([dict(unsafe_label=0,review=dict(decision="allow"))])
    report=dict(decision_latency={"read":dict(input_tokens=150,first_decision_core_ms=100,subsequent=dist,below15=2,measured=2)},
        measurement=dict(encoder={name:dict(subsequent=dist) for name in ("read","payment")},
            diagnostics={name:dict(subsequent=dict(median_ms=300)) for name in ("read-review","payment-review")},hardware=dict(device="test")),
        accuracy={"development":dict(classifier=accuracy,llm=accuracy)},cards=[],missing_native_cases=["missing"],external_harness_verdict="insufficient_evidence",external_errors=0,
        budget=dict(local=1,external=1,accounted_with_holds_usd="0.50"),paths=dict(measurement="m",native="n",reviews="r"),matrix_sha256="hash",reviewer_prompt_version="v2",reviewer_prompt_sha256="prompt")
    text=render(report)
    assert "not native claim latency" in text and "not a pristine holdout" in text
    assert "Missing declared native cases" in text and "not reset/retry" in text
    assert "False allow" in text and "Below15ms" in text


def test_wiring_review_projection_preserves_counts_receipts_and_source_without_duplicate_blobs():
    from copy import deepcopy
    from src.benchmark.review import compact_observations
    record=dict(case_id="case",task_id="user_task_0",producer="acting_model",status="completed",trace_id="trace",child_run_id="run",model_attempts=1,tool_attempts=1,
        initial_fingerprint="before",final_fingerprint="after",measured=dict(utility=True),cleanup_errors=[],runtime_proof={},
        evidence=dict(initial_state="x"*20000,actions=[dict(tool="send_money",ticket="ticket",span_id="tool",status="executed",execution_receipt=dict(executed=True),output="x"*20000)]),
        store_events=[dict(kind="model_attempt",payload=dict(sequence=1,role="actor")),dict(kind="tool_attempt",payload=dict(ticket="ticket"))],
        trace_audit=dict(span_manifest=[dict(span_id="root",parent_id=None,name="root",span_type="AGENT")],score_provenance=[]))
    original=deepcopy(record);plan=dict(cases=[dict(case_id="case",kind="card"),dict(case_id="missing",kind="canary")])
    result=compact_observations(plan,[record]);view=result["records"][0]
    assert record==original and result["missing_declared_cases"]==["missing"]
    assert view["actions"][0]["execution_receipt"]["executed"] is True
    assert view["store_events"][0]["payload"]["sequence"]==1 and view["model_attempts"]==1
    assert view["full_record_artifact"]=="runs:/run/wiring/episode.json"
    assert len(json.dumps(result))<len(json.dumps(record))/2
