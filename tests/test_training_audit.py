import hashlib
import json

import pytest

from src.benchmark.training_audit import training_coverage,transfer_errors


def row(id,tool,label,*,partition="train",args=None):
    text=json.dumps(dict(goal="Synthetic request",action=dict(tool=tool,arguments=args or {}),benchmark_state={},
        untrusted_observations=["read_file doc.txt\nUntrusted prose"]))
    return dict(candidate_id=id,model_input=text,input_digest=hashlib.sha256(text.encode()).hexdigest(),unsafe_label=label,
        projection_supported=True,scenario_group="pair",partition=partition,tool=tool,document_group="family")


def test_saved_logits_audit_separates_read_and_mutation_errors_and_binds_labels():
    rows=[row("read","get_balance",0),row("write","send_money",1)]
    predictions=[dict(candidate_id=r["candidate_id"],input_digest=r["input_digest"],unsafe_label=r["unsafe_label"],logits=logits)
        for r,logits in zip(rows,[[0,3],[3,0]],strict=True)]
    result=transfer_errors(rows,predictions,dict(temperature=1,threshold=0.5))
    assert result["slices"]["reads"]["false_block"]==1
    assert result["slices"]["mutations"]["false_allow"]==1
    predictions[0]["unsafe_label"]=1
    with pytest.raises(ValueError,match="binding_mismatch"):transfer_errors(rows,predictions,dict(temperature=1,threshold=0.5))


def test_training_audit_counts_unused_documents_and_narrow_counterfactuals():
    rows=[row("positive","send_money",0,args={"recipient":"A"}),row("negative","send_money",1,args={"recipient":"B"})]
    result=training_coverage(rows,dict(train=[dict(document_id="doc"),dict(document_id="unused")]))
    assert result["read_examples"]==0 and result["paired_changed_fields"]=={"recipient":1}
    assert result["partitions"]["train"]["unused_documents"]==1
    rows[0]["model_input"]+=" "
    with pytest.raises(ValueError,match="input_digest_mismatch"):training_coverage(rows,{})
