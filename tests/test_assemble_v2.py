import pytest

from src.benchmark.assemble_v2 import quality_banks
from src.benchmark.bulk_v2 import STYLES,note_banks


def test_explicit_style_amendment_preserves_the_original_per_call_failure():
    notes=[];cases=[]
    for part,styles in STYLES.items():
        for style in styles:
            case_id=part+"-"+style;cases.append(dict(case_id=case_id,partition=part,style=style))
            for index in range(24):notes.append(dict(note_id=case_id+str(index),case_id=case_id,partition=part,style=style,
                text=case_id+" distinct note "+str(index),issues=[],adversarial_requested=index%2==0))
    cases.append(dict(case_id="failed-call",partition="train",style=STYLES["train"][0]))
    plan=dict(cases=cases,minimum_notes_per_partition=24,minimum_adversarial_notes_per_partition=8,minimum_notes_per_case=1)
    with pytest.raises(ValueError,match="case_coverage_failed"):note_banks(notes,[],plan)
    banks,duplicates=quality_banks(notes,plan)
    assert not duplicates and len(banks["calibration"])==48
    missing=[row for row in notes if row["style"]!=STYLES["calibration"][0]]
    with pytest.raises(ValueError,match="population_coverage|style_coverage"):quality_banks(missing,plan)
