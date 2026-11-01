"""Completion is an observed provider outcome, never a generated fallback."""
from copy import deepcopy

import pytest

from src.infra.serving_probe import completed_response
from src.infra.target_stack import redact


def response():
    return dict(status=200,body=dict(object="response",id="resp-fixture",status="completed",error=None,incomplete_details=None,
        output=[dict(id="msg-fixture",type="message",role="assistant",status="completed",content=[dict(type="output_text",text="Genuine fixture output.")])],
        usage=dict(total_tokens=10)))


def test_completed_text_has_final_content_and_no_pending_calls():
    body,calls,answer=completed_response(response())
    assert answer=="Genuine fixture output." and calls==[] and body["status"]=="completed"


@pytest.mark.parametrize("change",["http_error","incomplete","item_incomplete","empty","tool_markup","dangling_call","usage_missing","id_missing"])
def test_faults_or_unattested_output_cannot_count_as_completed(change):
    value=response();body=value["body"]
    if change=="http_error":value["status"]=500
    elif change=="incomplete":body["status"]="incomplete"
    elif change=="item_incomplete":body["output"][0]["status"]="in_progress"
    elif change=="empty":body["output"][0]["content"][0]["text"]=" "
    elif change=="tool_markup":body["output"][0]["content"][0]["text"]="<tool_call>partial"
    elif change=="dangling_call":body["output"]=[dict(type="function_call",status="completed",call_id="call",name="get_balance",arguments="{}")]
    elif change=="usage_missing":body.pop("usage")
    elif change=="id_missing":body.pop("id")
    with pytest.raises(RuntimeError):completed_response(value)


def test_structured_refusal_is_genuine_content_but_not_task_utility():
    value=response();value["body"]["output"][0]["content"]=[dict(type="refusal",refusal="Clarification required.")]
    assert completed_response(value)[2]=="Clarification required."


def test_schema_declarations_survive_known_secret_value_redaction():
    value=dict(schema=dict(properties=dict(password=dict(type="string",writeOnly=True))),arguments=dict(password="SYNTHETIC-SECRET"))
    original=deepcopy(value)
    result=redact(value,["SYNTHETIC-SECRET"])
    assert result["schema"]["properties"]["password"]==dict(type="string",writeOnly=True)
    assert result["arguments"]["password"]=="[WITHHELD]" and value==original
