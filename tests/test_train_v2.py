import pytest

from src.benchmark.train_v2 import paired_bootstrap,population_metrics,validate_fit_rows


def test_metrics_keep_read_and_write_failures_separate_and_bootstrap_pairs():
    rows=[dict(unsafe_label=label,tool=tool,scenario_group="case") for label,tool in [(0,"get_balance"),(0,"send_money"),(1,"send_money"),(1,"send_money")]]
    baseline=[[0,2],[0,2],[2,0],[0,2]];new=[[2,0],[2,0],[0,2],[0,2]];cal=dict(temperature=1,threshold=0.5)
    score=population_metrics(new,rows,cal)
    assert score["accuracy"]==1 and score["false_block_constraints_met"]
    assert score["strata"]["reads"]["false_block_rate"]==0
    result=paired_bootstrap(rows,baseline,cal,new,cal,replicates=10)
    assert result["differences_v2_minus_v1"]["accuracy"]["estimate"]==0.75


def test_fresh_challenge_cannot_enter_fit_population():
    with pytest.raises(ValueError,match="must_not_enter_fitting"):
        validate_fit_rows({"fresh_challenge":[]},{"cases":[]})
