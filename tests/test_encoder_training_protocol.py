from copy import deepcopy

import pytest

from src.benchmark.train_encoder import choose_threshold,metrics,verify_partitions


def rows():
    return [dict(partition=part,unsafe_label=label,original_benchmark_case=False,execution_error=None,projection_supported=True,
        scenario_group=part+"-pair",recipe_family=part+"-recipe",document_group=part+"-doc",input_digest=f"{part}-{label}")
        for part in ("train","calibration","validation") for label in (0,1)]


def test_partition_verification_preserves_pairs_and_rejects_leakage():
    source=rows();assert verify_partitions(source)["no_original_cases_fitted"]
    bad=deepcopy(source);bad[2]["document_group"]=bad[0]["document_group"]
    with pytest.raises(ValueError,match="cross_partition_leak"):verify_partitions(bad)
    with pytest.raises(ValueError):verify_partitions(source[:-1])
    bad=deepcopy(source);bad[0]["original_benchmark_case"]=True
    with pytest.raises(ValueError,match="ineligible"):verify_partitions(bad)


def test_threshold_uses_validation_false_block_constraint_not_test_outcomes():
    logits=[[3,0],[2,0],[0,2],[0,3]];labels=[0,0,1,1]
    threshold=choose_threshold(logits,labels,1.0,0.10)
    result=metrics(logits,labels,temperature=1.0,threshold=threshold)
    assert result["false_allows"]==result["false_blocks"]==0
    assert result["samples"]==4 and sum(b["count"] for b in result["reliability_bins"])==4
    with pytest.raises(ValueError,match="both_classes"):choose_threshold(logits[:2],[0,0],1.0)
