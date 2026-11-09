"""Synthetic unit logits are not a trained/calibrated banking-model claim."""
import math
import hashlib
import json

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
import pytest

from src.benchmark.guards import Calibration,ClassifierGuard,LLMGuard,ReviewInput,Verdict,paired_replay,timed_review


def value():return ReviewInput("Unit fixture goal","unit-policy","Unit policy only","echo",{"text":"fixture"},("untrusted fixture",))


def test_classifier_one_pass_uses_bound_temperature_and_threshold():
    seen=[]
    calibration=Calibration("unit-logit-fixture","unit-policy","unit-calibration",2.0,0.7)
    guard=ClassifierGuard(lambda text:(seen.append(text) or 2.0),calibration,model_id="unit-logit-fixture")
    result=guard.review(value())
    assert len(seen)==1 and result.decision=="block"
    assert math.isclose(result.risk,1/(1+math.exp(-1)))
    with pytest.raises(ValueError,match="model_mismatch"):ClassifierGuard(lambda _:0,calibration,model_id="wrong")
    with pytest.raises(ValueError,match="policy_mismatch"):
        guard.review(ReviewInput("goal","other-policy","policy","echo",{}))


def test_llm_guard_counts_request_and_receives_same_input_without_label():
    reservations=[]
    guard=LLMGuard(FakeMessagesListChatModel(responses=[AIMessage(content='{"allow":false}')]),guard_id="unit-LLM-fixture",reserve_model=lambda:reservations.append(1))
    assert guard.review(value()).decision=="block" and reservations==[1]


@pytest.mark.parametrize("text",['{"allow":"false"}','{"allow":true,"allow":false}','{"allow":true,"extra":1}','not JSON'])
def test_invalid_llm_verdict_is_error_not_a_correct_block(text):
    guard=LLMGuard(FakeMessagesListChatModel(responses=[AIMessage(content=text)]),guard_id="unit-LLM-fixture",reserve_model=lambda:None)
    row=timed_review(guard,value())
    assert row["decision"]=="error" and row["risk"] is None and row["review_latency_ns"]>=0


def test_same_action_replay_counterbalances_mode_order_and_preserves_errors():
    classifier=ClassifierGuard(lambda _:0,Calibration("unit-C","unit-policy","unit-cal",1,0.6),model_id="unit-C")
    llm=LLMGuard(FakeMessagesListChatModel(responses=[AIMessage(content='{"allow":true}')]),guard_id="unit-L",reserve_model=lambda:None)
    rows=paired_replay([("one",value(),False),("two",value(),True)],[classifier,llm])
    assert [r["guard_id"] for r in rows]==["unit-C","unit-L","unit-L","unit-C"]
    assert len({r["input_digest"] for r in rows})==1
    assert all(r["decision"]=="allow" for r in rows)


def test_mismatched_action_verdict_is_not_accepted_or_timed_as_success():
    class Bad:
        guard_id="unit-bad"
        def review(self,_):return Verdict("wrong-input","allow",self.guard_id)
    result=timed_review(Bad(),value())
    assert result["decision"]=="error" and result["error"]=="ValueError"


def test_encoder_rejects_legacy_head_and_changed_weights_without_downloading(tmp_path):
    from src.benchmark.encoder import manifest
    from src.benchmark.guards import INPUT_VERSION
    weights=tmp_path/"model.safetensors";weights.write_bytes(b"unit fixture, not real neural weights")
    for name in ("config.json","tokenizer_config.json","tokenizer.json"):
        (tmp_path/name).write_text("{}")
    value=dict(model_id="unit-model",input_version=INPUT_VERSION,policy_id="unit-policy",trained_for="banking-action-guard",unsafe_class_id=1,
        files={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in tmp_path.iterdir()})
    (tmp_path/"benchmark-guard.json").write_text(json.dumps(value))
    assert manifest(tmp_path,policy_id="unit-policy")["model_id"]=="unit-model"
    weights.write_bytes(b"changed")
    with pytest.raises(ValueError,match="hash_mismatch"):manifest(tmp_path,policy_id="unit-policy")
    value["trained_for"]="shell-command-guard";(tmp_path/"benchmark-guard.json").write_text(json.dumps(value))
    with pytest.raises(ValueError,match="incompatible"):manifest(tmp_path,policy_id="unit-policy")


def test_encoder_manifest_must_bind_all_consumed_files(tmp_path):
    from src.benchmark.encoder import manifest
    from src.benchmark.guards import INPUT_VERSION
    (tmp_path/"model.safetensors").write_bytes(b"fixture")
    (tmp_path/"benchmark-guard.json").write_text(json.dumps(dict(model_id="unit-model",input_version=INPUT_VERSION,
        policy_id="unit-policy",trained_for="banking-action-guard",unsafe_class_id=1,
        files={"model.safetensors":hashlib.sha256(b"fixture").hexdigest()})))
    with pytest.raises(ValueError,match="incomplete_export"):manifest(tmp_path,policy_id="unit-policy")


def test_partial_verifier_json_is_an_error_even_if_parseable():
    guard=LLMGuard(FakeMessagesListChatModel(responses=[AIMessage(content='{"allow":true}',
        response_metadata={"finish_reason":"length"})]),guard_id="unit-LLM-fixture",reserve_model=lambda:None)
    assert timed_review(guard,value())["decision"]=="error"


def test_timed_review_retains_bounded_verdict_text_and_calibration_context():
    # Presentation-only retention: the raw LLM verdict, prompt version and the
    # frozen classifier logit/temperature/threshold are recorded next to the
    # decision without changing any decision or timing semantics.
    llm=LLMGuard(FakeMessagesListChatModel(responses=[AIMessage(content='  {"allow":false}  ')]),
        guard_id="unit-LLM-fixture",reserve_model=lambda:None,prompt_version="v2")
    row=timed_review(llm,value())
    assert row["decision"]=="block" and row["raw_verdict"]=='  {"allow":false}  ' and row["prompt_version"]=="v2"
    assert "unsafe_logit" not in row and "temperature" not in row
    classifier=ClassifierGuard(lambda _:1.5,Calibration("unit-C","unit-policy","unit-cal",3.0,0.7),model_id="unit-C")
    row=timed_review(classifier,value())
    assert row["unsafe_logit"]==1.5 and row["temperature"]==3.0 and row["threshold"]==0.7
    assert "raw_verdict" not in row and "prompt_version" not in row
    assert math.isclose(row["risk"],1/(1+math.exp(-0.5)))


def test_llm_verdict_retention_is_bounded_and_absent_on_errors():
    long_json='{"allow":'+("true ")*200+'}'
    guard=LLMGuard(FakeMessagesListChatModel(responses=[AIMessage(content='{"allow":true,"extra":1}')]),
        guard_id="unit-LLM-fixture",reserve_model=lambda:None,prompt_version="v2")
    failed=timed_review(guard,value())
    assert failed["decision"]=="error" and "raw_verdict" not in failed
    class LongGuard(LLMGuard):
        def review(self,review_value):
            verdict=super().review(review_value)
            return Verdict(verdict.input_digest,verdict.decision,verdict.guard_id,raw_verdict=long_json)
    bounded=timed_review(LongGuard(FakeMessagesListChatModel(responses=[AIMessage(content='{"allow":true}')]),
        guard_id="unit-LLM-fixture",reserve_model=lambda:None),value())
    assert len(bounded["raw_verdict"])<=256
