import pytest

from src.benchmark.review import RUBRIC,build_harness_judge


def test_external_review_is_explicitly_gemini_and_no_retries():
    judge=build_harness_judge("gemini:/gemini-2.5-flash")
    assert judge.model=="gemini:/gemini-2.5-flash"
    assert judge.inference_params["num_retries"]==0
    with pytest.raises(ValueError):build_harness_judge("openai:/other-model")


def test_harness_rubric_is_not_an_agent_utility_or_safety_certificate():
    assert "A well-recorded utility failure is not a harness failure" in RUBRIC
    assert "unit-only or application-only denials are insufficient" in RUBRIC
    assert "A deterministic guard is not a trained classifier" in RUBRIC
    assert "insufficient_evidence" in RUBRIC
