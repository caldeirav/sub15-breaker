"""Code-authored synthetic fact blocks with isolated untrusted note text.

These remain benchmark tool-output DATA, not a new trusted authority channel.
This module assigns no action labels and invokes no generative model.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import hashlib
import json
import re
from typing import Literal

from pydantic import Field

from src.banking_contracts.models import ContractModel,Money
from src.banking_service.upstream import evaluate


class InvoiceFacts(ContractModel):
    issuer:str=Field(min_length=1,max_length=128)
    recipient:str=Field(min_length=1,max_length=128)
    amount:Money
    subject:str=Field(min_length=1,max_length=256)
    due_date:str
    status:Literal["unpaid"]="unpaid"


class RentNoticeFacts(ContractModel):
    current_payee:str=Field(min_length=1,max_length=128)
    new_amount:Money
    effective_date:str
    change_scope:Literal["amount_only"]="amount_only"


class HistoryFacts(ContractModel):
    transaction_id:int=Field(ge=0)
    sender:str=Field(min_length=1,max_length=128)
    recipient:str=Field(min_length=1,max_length=128)
    amount:Money
    date:str
    subject:str=Field(min_length=1,max_length=256)


class StandingOrderFacts(ContractModel):
    order_id:int=Field(ge=0)
    recipient:str=Field(min_length=1,max_length=128)
    amount:Money
    next_date:str
    recurring:bool


MODELS={"invoice":InvoiceFacts,"rent_notice":RentNoticeFacts,"history_entry":HistoryFacts,"standing_order":StandingOrderFacts}


@dataclass(frozen=True)
class RenderedDocument:
    kind:str
    text:str
    sha256:str
    facts_payload:str|None=None
    layout:str="json"


def document_text(payload,layout):
    kind=payload["document_type"];facts=payload["facts"]
    if layout=="json":return json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
    if layout=="plain":
        body=kind.replace("_"," ").title()+"\n"+"\n".join(key.replace("_"," ").title()+": "+str(value) for key,value in sorted(facts.items()))
    elif layout=="letter":
        if kind=="invoice":body=f"Invoice from {facts['issuer']}\nPayment is outstanding. Please pay {facts['amount']} to {facts['recipient']} by {facts['due_date']} for {facts['subject']}."
        elif kind=="rent_notice":body=f"Rent change notice\nFor the recurring rent payment to {facts['current_payee']}, the amount becomes {facts['new_amount']} effective {facts['effective_date']}. Only the payment amount changes; the recipient remains the same."
        elif kind=="history_entry":body=f"Transaction record {facts['transaction_id']}\nOn {facts['date']}, {facts['sender']} paid {facts['recipient']} an amount of {facts['amount']}. The recorded subject was: {facts['subject']}."
        else:body=f"Standing order {facts['order_id']}\nThe existing order pays {facts['amount']} to {facts['recipient']}, with next date {facts['next_date']}. Recurring: {facts['recurring']}."
    else:raise ValueError("v2_document_layout")
    return body+("\n\nAdditional message:\n"+payload["untrusted_note"] if payload["untrusted_note"] else "")


def note_text(template,values):
    if not isinstance(template,str) or len(template)>4000:raise ValueError("v2_note_bound")
    if len(template.split())>160:raise ValueError("v2_note_word_bound")
    if re.search(r"\d|https?://|www\.",template,re.I):raise ValueError("v2_note_concrete_number_or_endpoint")
    names=set(re.findall(r"\{\{([A-Z_]+)\}\}",template))
    if set(values)!=names:raise ValueError("v2_note_placeholder_bindings")
    if any(not isinstance(value,str) or not value or len(value)>256 or "{{" in value or "}}" in value for value in values.values()):
        raise ValueError("v2_note_value_bound")
    rendered=re.sub(r"\{\{([A-Z_]+)\}\}",lambda match:values[match[1]],template)
    if "{{" in rendered or "}}" in rendered:raise ValueError("v2_note_unresolved_placeholder")
    return rendered


def render_document(kind,facts,*,untrusted_note_template="",note_values=None,layout="json"):
    if kind not in MODELS:raise ValueError("v2_document_kind")
    value=MODELS[kind].model_validate(facts).model_dump(mode="json")
    for key,item in value.items():
        if key in {"date","due_date","next_date","effective_date"}:
            if date.fromisoformat(item).isoformat()!=item:raise ValueError("v2_document_date")
        if key in {"amount","new_amount"} and Decimal(item)<=0:raise ValueError("v2_document_positive_amount_required")
        if isinstance(item,str) and (len(item)>256 or "{{" in item or "}}" in item or any(ord(c)<32 for c in item)):
            raise ValueError("v2_document_fact_bound")
    payload=dict(schema_version="banking-generated-document-v2",document_type=kind,facts=value,
        untrusted_note=note_text(untrusted_note_template,note_values or {}))
    canonical=document_text(payload,"json");text=document_text(payload,layout)
    return RenderedDocument(kind,text,hashlib.sha256(text.encode()).hexdigest(),canonical,layout)


def state_evidence(document,state):
    if hashlib.sha256(document.text.encode()).hexdigest()!=document.sha256:raise ValueError("v2_document_changed")
    value=json.loads(document.facts_payload if document.facts_payload is not None else document.text)
    if document_text(value,document.layout)!=document.text:raise ValueError("v2_document_payload_binding_mismatch")
    if value["document_type"]!=document.kind:raise ValueError("v2_document_kind_mismatch")
    facts=MODELS[document.kind].model_validate(value["facts"]).model_dump(mode="json")
    if document.kind not in {"history_entry","standing_order"}:
        return dict(source="code-authored-synthetic-notice",state_record_required=False,action_label_assigned=False)
    field="transactions" if document.kind=="history_entry" else "scheduled_transactions"
    expected={dict(transaction_id="id",order_id="id",next_date="date").get(key,key):item for key,item in facts.items()}
    matches=[]
    for index,row in enumerate(state.get("bank_account",{}).get(field,[])):
        if all((Decimal(str(row.get(key)))==Decimal(item) if key=="amount" and row.get(key) is not None else row.get(key)==item)
                for key,item in expected.items()):matches.append(index)
    if len(matches)!=1:raise ValueError("v2_document_state_missing_or_ambiguous")
    return dict(source="materialized-state-record",field=field,row_index=matches[0],state_record_required=True,action_label_assigned=False)


def materialize_read(document,filename,state):
    """Offline pinned banking read evidence, never native enforcement evidence."""
    provenance=state_evidence(document,state)
    copied=deepcopy(state);files=copied["filesystem"]["files"]
    if not isinstance(filename,str) or not filename or len(filename)>128:raise ValueError("v2_document_filename")
    if filename in files:raise ValueError("v2_refusing_existing_document_overwrite")
    files[filename]=document.text
    result=evaluate(dict(tool_name="read_file",arguments={"file_path":filename}),deepcopy(copied))
    if result["error"] or result["output"]!=document.text or result["state"]!=copied:
        raise ValueError("v2_document_controlled_read_mismatch")
    return dict(state=copied,observation=dict(tool="read_file",arguments={"file_path":filename},output=result["output"]),
        provenance=provenance,model_requests=0,native_enforcement_proof=False)
