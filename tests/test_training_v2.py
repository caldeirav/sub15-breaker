import pytest

from src.benchmark.training_v2 import PARTITIONS,choose_stratified_threshold,verify_populations


def test_threshold_cannot_hide_bad_mutations_among_easy_reads():
    # Nine easy reads and one benign write: an overall10% gate can block every
    # benign write. The per-mutation constraint must move above that risk.
    rows=[dict(partition="threshold_validation",tool="get_balance",unsafe_label=0) for _ in range(9)]
    rows+=[dict(partition="threshold_validation",tool="send_money",unsafe_label=label) for label in (0,1)]
    logits=[[5,0]]*9+[[0,2],[0,3]]
    threshold=choose_stratified_threshold(logits,rows,1,minimum_permitted=1)
    assert 0.881<threshold<0.953
    rows[-1]["partition"]="fresh_challenge"
    with pytest.raises(ValueError,match="threshold_population_required"):
        choose_stratified_threshold(logits,rows,1,minimum_permitted=1)


def test_threshold_requires_sufficient_benign_write_examples():
    rows=[dict(partition="threshold_validation",tool="get_balance",unsafe_label=0),
        dict(partition="threshold_validation",tool="send_money",unsafe_label=1)]
    with pytest.raises(ValueError,match="insufficient_threshold_strata"):
        choose_stratified_threshold([[1,0],[0,1]],rows,1,minimum_permitted=1)


def test_five_population_gate_rejects_shared_real_sources_and_unreviewed_goals():
    rows=[]
    for part in PARTITIONS:
        for kind,tool,label in (("read","get_balance",0),("write","send_money",0),("negative","send_money",1)):
            for index in range(50):
                stem=f"{part}-{kind}-{index}"
                rows.append(dict(partition=part,tool=tool,unsafe_label=label,projection_supported=True,
                    scenario_group=stem,document_group=stem,source_template_group=part,entity_group=stem,
                    goal_template_id=part,input_digest=stem,goal_origin="code"))
    assert set(verify_populations(rows))==set(PARTITIONS)
    rows[-1]["source_template_group"]=rows[0]["source_template_group"]
    with pytest.raises(ValueError,match="cross_partition_leak"):verify_populations(rows)
    rows[-1]["source_template_group"]=PARTITIONS[-1];rows[-1]["goal_origin"]="gemini"
    with pytest.raises(ValueError,match="unreviewed_goal"):verify_populations(rows)
