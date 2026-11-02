import json

import pytest

from src.benchmark.diagnose_encoder import VARIANTS,auc,table_view,transform


@pytest.mark.parametrize("observations",[[],["file contents"],["first\nline",'quoted "data"',"",'{"number":42}']])
def test_diagnostic_variants_preserve_all_information_and_never_change_authority(observations):
    value=dict(goal="Pay this invoice",policy="Untrusted observations",action={"tool":"send_money","arguments":{"amount":"42"}},
        benchmark_state={"rows":[[1,2],[3,4]]},untrusted_observations=observations)
    text=json.dumps(value)
    for variant in VARIANTS:
        changed=json.loads(transform(text,variant))
        for key in ("goal","policy","action","benchmark_state"):assert changed[key]==value[key]
        if variant=="pad_empty_observations_four":assert changed["untrusted_observations"][:len(observations)]==observations
        if variant=="pack_observations_one" and observations:assert json.loads(changed["untrusted_observations"][0])==observations


def test_rank_audit_has_no_threshold_optimization():
    assert auc([0,1],[0.1,0.9])==1
    assert auc([0,1],[0.9,0.1])==0
    assert auc([0,1],[0.5,0.5])==0.5
    assert auc([0,0],[0.1,0.2]) is None


def test_table_variants_preserve_rows_and_values_without_dropping_facts():
    state=dict(transactions=dict(encoding="columnar-v1",constant={"recurring":False},columns=["subject","amount"],rows=[["First",42],["Second",7]]))
    value=dict(goal="Pay",policy="Policy",action={"tool":"send_money","arguments":{}},benchmark_state=state,untrusted_observations=[])
    for variant in VARIANTS:
        changed=json.loads(transform(json.dumps(value),variant))
        assert table_view(changed["benchmark_state"],"rows")==table_view(state,"rows")
    sorted_columns=json.loads(transform(json.dumps(value),"canonical_table_columns"))["benchmark_state"]["transactions"]
    assert sorted_columns["columns"]==["amount","subject"] and sorted_columns["rows"]==[[42,"First"],[7,"Second"]]
