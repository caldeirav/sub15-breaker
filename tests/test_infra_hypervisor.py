"""The hypervisor helper has its own compatibility/stability prerequisites."""
import json
from types import SimpleNamespace

import pytest

from src.infra import doctor


@pytest.mark.parametrize("version,accepted",[("1.1.1",False),("1.3.0",False),("1.3.1",True),("1.3.2",True),("1.3.10",True)])
def test_old_libkrun_helpers_fail_even_with_current_podman(tmp_path,monkeypatch,version,accepted):
    helper=tmp_path/"krunkit";helper.write_bytes(b"fixture-only")
    calls=[]
    monkeypatch.setattr(doctor.platform,"system",lambda:"Darwin")
    monkeypatch.delitem(doctor.VERSIONS,"krunkit",raising=False)
    def run(args,**kwargs):
        calls.append(args)
        if args[:3]==["podman","machine","info"]:
            return SimpleNamespace(stdout=json.dumps({"Host":{"VMType":"libkrun"},"Version":{"Version":"6.1.4"}}))
        if args[:2]==["ps","-Ao"]:return SimpleNamespace(stdout="123 "+str(helper)+"\n")
        if args[0]=="lsof":return SimpleNamespace(stdout=f"p123\nftxt\ni{helper.stat().st_ino}\nn{helper}\n")
        assert args==[helper,"--version"]
        return SimpleNamespace(stdout="krunkit "+version)
    monkeypatch.setattr(doctor,"run",run)
    if accepted:doctor.check_hypervisor()
    else:
        with pytest.raises(RuntimeError,match="reboot/control-API"):doctor.check_hypervisor()
    assert all("start" not in args and "stop" not in args and "install" not in args for args in calls)


def test_updated_disk_binary_cannot_impersonate_an_old_running_hypervisor(tmp_path,monkeypatch):
    helper=tmp_path/"krunkit";helper.write_bytes(b"new helper")
    monkeypatch.setattr(doctor.platform,"system",lambda:"Darwin")
    def run(args,**kwargs):
        if args[:3]==["podman","machine","info"]:return SimpleNamespace(stdout='{"Host":{"VMType":"libkrun"}}')
        if args[:2]==["ps","-Ao"]:return SimpleNamespace(stdout="123 "+str(helper)+"\n")
        if args[0]=="lsof":return SimpleNamespace(stdout=f"p123\nftxt\ni{helper.stat().st_ino+1}\nn{helper}\n")
        pytest.fail("Installed --version was trusted without matching loaded code")
    monkeypatch.setattr(doctor,"run",run)
    with pytest.raises(RuntimeError,match="does not map"):doctor.check_hypervisor()


def test_non_macos_profile_does_not_execute_host_helper(monkeypatch):
    monkeypatch.setattr(doctor.platform,"system",lambda:"Linux")
    monkeypatch.setattr(doctor,"run",lambda *args,**kwargs:pytest.fail("unexpected host probe"))
    doctor.check_hypervisor()


def test_stopped_vm_cannot_pass_using_an_unrelated_new_host_helper(monkeypatch):
    monkeypatch.setattr(doctor.platform,"system",lambda:"Darwin")
    def run(args,**kwargs):
        if args[:3]==["podman","machine","info"]:
            return SimpleNamespace(stdout=json.dumps({"Host":{"VMType":"libkrun","MachineState":"Stopped"}}))
        if args[:2]==["ps","-Ao"]:return SimpleNamespace(stdout="COMMAND\n")
        pytest.fail("probed an unrelated helper instead of the running runtime")
    monkeypatch.setattr(doctor,"run",run)
    with pytest.raises(RuntimeError,match="No running"):
        doctor.check_hypervisor()


@pytest.mark.parametrize("client,server,accepted",[("5.8.9","5.8.9",True),("5.8.9","5.8.1",False),("5.8.9","",False),("5.8.9-rc.1","5.8.9-rc.1",False)])
def test_host_and_guest_versions_must_both_be_observed_and_match(monkeypatch,client,server,accepted):
    monkeypatch.setattr(doctor,"run",lambda *args,**kwargs:SimpleNamespace(stdout=json.dumps({"Client":{"Version":client},"Server":{"Version":server}})))
    monkeypatch.setitem(doctor.VERSIONS,"podman","v5.8.9")
    if accepted:doctor.check_podman_versions()
    else:
        with pytest.raises(RuntimeError):doctor.check_podman_versions()
