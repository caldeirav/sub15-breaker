"""Health/model listings and old partial evidence cannot satisfy qualification."""
import json
import os
import sys
import time

import pytest

from src.infra import doctor,qualification


def test_missing_stale_and_future_evidence_fail_closed(tmp_path):
    path=tmp_path/"qualification.json"
    with pytest.raises(RuntimeError,match="missing"):qualification.fresh_json(path)
    path.write_text('{"automated_passed":true}')
    assert qualification.fresh_json(path)["automated_passed"] is True
    for timestamp in [time.time()-90000,time.time()+3600]:
        os.utime(path,(timestamp,timestamp))
        with pytest.raises(RuntimeError,match="stale_or_future"):qualification.fresh_json(path)


def test_narrow_scope_report_cannot_stand_in_for_full_target_stack(tmp_path,monkeypatch):
    monkeypatch.setattr(qualification,"DIRECTORY",tmp_path)
    (tmp_path/"qualification.json").write_text(json.dumps(dict(scope="network-policy-controls-only",automated_passed=True)))
    with pytest.raises(RuntimeError,match="full_target_qualification"):
        qualification.require_current_cached(object())


def test_matching_package_version_does_not_hide_a_different_guest_image(monkeypatch):
    expected=qualification.VERSIONS["machine_os_image"]
    value=dict(deployments=[dict(booted=True,version=qualification.VERSIONS["machine_os_version"],**{"container-image-reference":"ostree-unverified-image:docker://"+expected})])
    monkeypatch.setattr(qualification.subprocess,"check_output",lambda *args,**kwargs:json.dumps(value))
    assert qualification.current_guest_os()["version"]==qualification.VERSIONS["machine_os_version"]
    value["deployments"][0]["container-image-reference"]="ostree-unverified-image:docker://quay.io/podman/machine-os:5.8"
    with pytest.raises(RuntimeError,match="reviewed_digest"):qualification.current_guest_os()


@pytest.mark.parametrize("args",[["doctor","--target-stack"],["doctor","--target-stack","--cluster","breaker-substrate","--skip-substrate"]])
def test_target_doctor_requires_the_full_managed_cluster_profile(monkeypatch,args):
    monkeypatch.setattr(sys,"argv",args)
    monkeypatch.setattr(doctor,"check_tools",lambda:pytest.fail("invalid command reached live probes"))
    with pytest.raises(SystemExit) as error:doctor.main()
    assert error.value.code==2
