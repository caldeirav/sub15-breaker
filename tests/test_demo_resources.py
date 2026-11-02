from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from src.benchmark.deployment import temporary_bridge


class Cluster:
    def __init__(self):
        self.resources={};self.deleted=[]
    def kubectl(self,*args,**kwargs):
        if args[0]=="get":
            item=self.resources.get((args[1],args[2]))
            return SimpleNamespace(stdout=json.dumps(item) if item else "")
        if args[0]=="delete":
            self.deleted.append((args[1],args[2]));del self.resources[(args[1],args[2])]
        elif args[0]=="replace":
            item=json.loads(args[2].read_text());self.resources[(item["kind"],item["metadata"]["name"])]=item
        else:raise AssertionError(args)
    def get(self,kind,name,*args):return deepcopy(self.resources[(kind,name)])


def test_temporary_resources_restore_original_spec_metadata_and_delete_only_new(monkeypatch,tmp_path):
    cluster=Cluster();key=("HTTPRoute","benchmark-banking-mcp")
    original=dict(kind=key[0],metadata=dict(name=key[1],uid="old",labels=dict(owner="ours")),spec=dict(timeout="old"))
    cluster.resources[key]=deepcopy(original)
    def configure(cluster,*args,**kwargs):
        for kind,name in [("AgentgatewayBackend","benchmark-banking-mcp"),key,("AgentgatewayPolicy","benchmark-banking-mcp"),("NetworkPolicy","benchmark-gateway-host-bridge")]:
            cluster.resources[(kind,name)]=dict(kind=kind,metadata=dict(name=name,uid="old" if kind=="HTTPRoute" else kind,
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
            cluster.resources[(kind,name)]=dict(kind=kind,metadata=dict(name=name,uid=kind),spec={})
    monkeypatch.setattr("src.benchmark.deployment.configure_bridge",configure)
    key=("AgentgatewayBackend","benchmark-banking-mcp")
    with pytest.raises(RuntimeError,match="concurrent_change"):
        with temporary_bridge(cluster,tmp_path,"host",8172,request_timeout=85,backend_timeout=75):
            cluster.resources[key]["spec"]["foreign_edit"]=True
    assert cluster.resources[key]["spec"]["foreign_edit"] and not cluster.deleted
