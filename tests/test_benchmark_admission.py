from types import SimpleNamespace

import pytest

from src.benchmark.admission import ReviewBuilder,classifier_guard
from src.benchmark.projection import POLICY_ID,project


def test_review_builder_uses_service_goal_state_and_only_completed_reads():
    snapshot=dict(context=dict(user_request="Read the statement"),state={})
    actions=[dict(tool="read_file",arguments={"file_path":"statement"},output="untrusted note",status="executed"),
        dict(tool="read_file",arguments={"file_path":"absent"},output="not read",status="error"),
        dict(tool="update_user_info",arguments={"city":"Other"},output="not a read",status="executed")]
    builder=ReviewBuilder(lambda text,**kw:{"input_ids":list(text)})
    value=builder(snapshot,"read_file",{"file_path":"statement"},actions)
    expected=project("Read the statement","read_file",{"file_path":"statement"},state={},observations=[
        dict(tool="read_file",arguments={"file_path":"statement"},output="untrusted note")],token_count=len,maximum_tokens=2048)
    assert value.value.serialized()==expected.value.serialized()
    assert value.value.policy_id==POLICY_ID
    assert "not read" not in value.value.serialized() and "not a read" not in value.value.serialized()


def test_review_builder_reports_overflow_without_truncating():
    builder=ReviewBuilder(lambda text,**kw:{"input_ids":list(text)},maximum=1)
    result=builder(dict(context=dict(user_request="Read"),state={}),"read_file",{"file_path":"statement"},[])
    assert "encoder_context_overflow" in result.issues
    assert "statement" in result.value.serialized()


def test_classifier_factory_rejects_calibration_not_bound_to_export(monkeypatch):
    monkeypatch.setattr("src.benchmark.admission.EncoderLogit",lambda *args,**kwargs:SimpleNamespace(manifest={"calibration":{"temperature":1}}))
    with pytest.raises(ValueError,match="frozen_calibration_mismatch"):
        classifier_guard("unused",{"temperature":2})
