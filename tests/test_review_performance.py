from src.benchmark.performance import case_comparisons,compare_reviews


def record(ms,decision="allow",digest="same",**kw):
    return dict(evidence=dict(actions=[dict(guard=dict(input_digest=digest,review_latency_ns=ms*1000000,decision=decision,error=None,**kw))]))


def test_only_completed_identical_input_reviews_have_a_comparison():
    result=compare_reviews([record(10)],[record(2000)])
    assert result["pairs"][0]["llm_over_classifier_ratio"]==200
    assert result["complete_admission_latency_claim"] is False and result["safety_equivalence_claim"] is False
    assert result["sub15ms_demonstrated"] is False


def test_timeout_is_not_a_successful_llm_latency_or_a_speedup():
    result=compare_reviews([record(54)],[record(20000,"error")])
    assert result["status"]=="insufficient_completed_pairs" and result["pairs"]==[]
    assert len(result["excluded"])==1


def test_no_pairing_different_inputs_or_cherry_picking_repeated_inputs():
    result=compare_reviews([record(10),record(20)],[record(1000,"error"),record(2000),record(30,digest="other")])
    assert len(result["pairs"])==1 and result["pairs"][0]["occurrence"]==1
    assert result["pairs"][0]["classifier_review_ms"]==20
    assert len(result["excluded"])==2


def test_fault_controls_and_nonfinite_durations_are_never_a_speedup():
    fault=record(1);fault["guard_control"]="allow"
    assert compare_reviews([fault],[record(1000)])["pairs"]==[]
    assert compare_reviews([record(float("nan"))],[record(1000)])["pairs"]==[]


def test_canary_durations_cannot_be_paired_against_a_real_agent_card():
    left=record(10);left["case_id"]="canary"
    right=record(2000);right["case_id"]="agent"
    plan=dict(cases=[dict(case_id="canary",kind="canary",arm="classifier"),dict(case_id="agent",kind="card",card_id="D01",arm="llm")])
    result=case_comparisons(plan,[left,right])
    assert set(result)=={"scripted_canary","D01"}
    assert all(group["status"]=="insufficient_completed_pairs" for group in result.values())
