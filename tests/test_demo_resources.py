from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from src.benchmark.deployment import resource_patch,temporary_bridge


class Cluster:
    def __init__(self):
        self.resources={};self.deleted=[]
    def kubectl(self,*args,**kwargs):
        if args[0]=="get":
            item=self.resources.get((args[1],args[2]))
            return SimpleNamespace(stdout=json.dumps(item) if item else "")
        if args[0]=="delete":
            self.deleted.append((args[1],args[2]));del self.resources[(args[1],args[2])]
        elif args[0]=="patch":
            item=self.resources[(args[1],args[2])]
            for op in json.loads(args[-1].read_text()):
                path=op["path"].strip("/").split("/");target=item
                for part in path[:-1]:target=target[part]
                if op["op"]=="test":assert target[path[-1]]==op["value"]
                elif op["op"]=="remove":target.pop(path[-1])
                else:target[path[-1]]=op["value"]
        else:raise AssertionError(args)
    def get(self,kind,name,*args):return deepcopy(self.resources[(kind,name)])


def test_temporary_resources_restore_original_spec_metadata_and_delete_only_new(monkeypatch,tmp_path):
    cluster=Cluster();key=("HTTPRoute","benchmark-banking-mcp")
    original=dict(kind=key[0],metadata=dict(name=key[1],uid="old",resourceVersion="1",labels=dict(owner="ours")),spec=dict(timeout="old"))
    cluster.resources[key]=deepcopy(original)
    def configure(cluster,*args,**kwargs):
        for kind,name in [("AgentgatewayBackend","benchmark-banking-mcp"),key,("AgentgatewayPolicy","benchmark-banking-mcp"),("NetworkPolicy","benchmark-gateway-host-bridge")]:
            cluster.resources[(kind,name)]=dict(kind=kind,metadata=dict(name=name,uid="old" if kind=="HTTPRoute" else kind,resourceVersion="1",
                labels=dict(owner="ours"),annotations=dict(applied="yes")),spec=dict(timeout="new"),status=dict(accepted=True))
    monkeypatch.setattr("src.benchmark.deployment.configure_bridge",configure)
    with pytest.raises(ValueError,match="body failure"):
        with temporary_bridge(cluster,tmp_path,"host",8172,request_timeout=85,backend_timeout=75):
            cluster.resources[key]["status"]=dict(accepted=False)
            raise ValueError("body failure")
    assert len(cluster.deleted)==3 and list(cluster.resources)==[key]
    assert cluster.resources[key]["spec"]==original["spec"] and cluster.resources[key]["metadata"]==original["metadata"]
    assert json.loads((tmp_path/"bridge-restoration.json").read_text())["restored"]


def test_restore_refuses_concurrent_spec_change(monkeypatch,tmp_path):
    cluster=Cluster()
    def configure(cluster,*args,**kwargs):
        for kind,name in [("AgentgatewayBackend","benchmark-banking-mcp"),("HTTPRoute","benchmark-banking-mcp"),("AgentgatewayPolicy","benchmark-banking-mcp"),("NetworkPolicy","benchmark-gateway-host-bridge")]:
            cluster.resources[(kind,name)]=dict(kind=kind,metadata=dict(name=name,uid=kind,resourceVersion="1"),spec={})
    monkeypatch.setattr("src.benchmark.deployment.configure_bridge",configure)
    key=("AgentgatewayBackend","benchmark-banking-mcp")
    with pytest.raises(RuntimeError,match="concurrent_change"):
        with temporary_bridge(cluster,tmp_path,"host",8172,request_timeout=85,backend_timeout=75):
            cluster.resources[key]["spec"]["foreign_edit"]=True
    assert cluster.resources[key]["spec"]["foreign_edit"] and not cluster.deleted


def test_cas_patch_preserves_annotations_without_serializing_live_metadata():
    annotation='{"metadata":{"resourceVersion":"historical"},"status":{}}'
    current=dict(metadata=dict(uid="uid",resourceVersion="42",annotations={"kubectl.kubernetes.io/last-applied-configuration":annotation}),spec=dict(old=True),status={})
    desired=deepcopy(current);desired["spec"]={"new":True}
    operations=resource_patch(current,desired)
    assert operations[:2]==[dict(op="test",path="/metadata/uid",value="uid"),dict(op="test",path="/metadata/resourceVersion",value="42")]
    assert not any(op["path"] in {"/status","/metadata"} for op in operations)
    assert operations[-1]["value"]==current["metadata"]["annotations"]
