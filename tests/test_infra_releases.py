"""Release freshness is not live-runtime acceptance or upgrade authorization."""
from datetime import date

import pytest

from src.infra.releases import assess, audit, release_version


def release(tag, **changes):
    return dict(tag_name=tag, draft=False, prerelease=False, html_url="https://example.invalid/release", **changes)


def test_maintained_line_does_not_silently_select_another_major_or_prerelease():
    spec=dict(name="helm",pin="helm",line=[3])
    releases=[release("v3.22.1"),release("v4.3.1"),dict(release("v3.23.0"),prerelease=True)]
    result=assess(spec,{"helm":"v3.20.1"},releases,date(2026,11,1))
    assert result["latest_in_reviewed_line"]=="v3.22.1"
    assert result["status"]=="update_required" and result["passed"] is False
    assert result["installed_runtime_observed"] is False


def test_explicit_exception_expires_and_does_not_hide_drift():
    spec=dict(name="kubernetes",pin="kubectl",line=[1,37],exception="owner-approved retention",exception_until="2026-11-08")
    result=assess(spec,{"kubectl":"v1.37.0"},[release("v1.37.2")],date(2026,11,1))
    assert result["status"]=="exception_active" and result["drift"] is True and result["passed"] is True
    assert assess(spec,{"kubectl":"v1.37.0"},[release("v1.37.2")],date(2026,11,9))["passed"] is False


def test_release_candidates_require_explicit_policy_and_final_sorts_after_rc():
    assert release_version("v1.0.0-rc.1") is None
    assert release_version("v1.0.0",True)>release_version("v1.0.0-rc.1",True)
    spec=dict(name="substrate",pin="substrate",line=[1],allow_published_rc=True)
    assert assess(spec,{"substrate":"v1.0.0-rc.1"},[release("v1.0.0-rc.1")],date(2026,11,1))["passed"] is True
    assert assess(spec,{"substrate":"v1.0.0-rc.1"},[release("v1.0.0")],date(2026,11,1))["passed"] is False


def test_release_lookup_failure_and_overdue_manual_checks_fail_closed():
    policy=dict(review_due="2026-11-08",manual_release_checks=["effective model runtime"],components=[dict(name="kind",pin="kind",repo="example/kind",line=[0])])
    def fail(_):raise RuntimeError("do-not-echo-token")
    result=audit(policy,{"kind":"v0.33.0"},fetch=fail,today=date(2026,11,1))
    assert result["passed"] is False and result["results"][0]["status"]=="unverified"
    assert "do-not-echo-token" not in str(result)
    result=audit(policy,{"kind":"v0.33.0"},fetch=lambda _:[release("v0.33.0")],today=date(2026,11,9))
    assert result["manual_review_overdue"] is True and result["passed"] is False


@pytest.mark.parametrize("configured",["v4.3.1","v3.99.0"])
def test_wrong_line_or_unverified_future_pin_cannot_pass(configured):
    with pytest.raises(ValueError):
        assess(dict(name="helm",pin="helm",line=[3]),{"helm":configured},[release("v3.22.1")],date(2026,11,1))
