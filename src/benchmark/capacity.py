"""Authenticated capacity gates and payload-free durable-history preservation evidence."""
import argparse
import hashlib
import json
from pathlib import Path

from src.benchmark.deployment import private
from src.integrations.agentdojo.inventory import digest


def validate_capacity(view,plan,*,binding,minimum_trials):
    wanted=plan["capacity"];campaign=view.get("campaign") or {}
    if (view.get("schema_version")!="banking-capacity-v1" or view.get("limits")!=wanted["store_limits"] or
            campaign.get("id")!=wanted["campaign_id"] or campaign.get("binding")!=binding or campaign.get("limits")!=wanted["requirements"]):
        raise RuntimeError("capacity_binding_differs")
    used=campaign.get("used",{});limits=campaign["limits"]
    if set(used)!=set(limits) or any(type(v) is not int or not 0<=v<=limits[k] for k,v in used.items()):raise RuntimeError("capacity_usage_unobserved")
    if limits["trials"]-used["trials"]<minimum_trials:raise RuntimeError("capacity_trials_insufficient")
    if any(type(view.get("available",{}).get(k)) is not int or view["available"][k]<limits[k]-used[k] for k in limits):
        raise RuntimeError("capacity_headroom_insufficient")
    return view


def require_capacity(store,budget,plan,directory,*,minimum_trials):
    namespace=plan.get("rehearsal_of") or plan["namespace"]
    campaign=json.loads((budget.directory/("demo-campaign-"+namespace+".json")).read_text())
    expected=digest(dict(qualification=campaign["qualification_sha256"],rehearsal=campaign["rehearsal_sha256"]))
    view=validate_capacity(store.call("/capacity",{}),plan,binding=expected,minimum_trials=minimum_trials)
    private(Path(directory)/"capacity-readiness.json",view)
    return view


def history_snapshot(deployment):
    # Only counts/hashes leave the store. No database copy, key or banking payload is exported.
    code='''import os,sqlite3,json,hashlib
db=sqlite3.connect("file:"+os.environ["BANKING_STORE_PATH"]+"?mode=ro",uri=True)
db.execute("PRAGMA query_only=ON");db.execute("BEGIN")
result={}
for table,key in (("metadata","name"),("trials","id"),("actions","ticket"),("outbox","id")):
 rows=db.execute("SELECT * FROM "+table+" ORDER BY "+key).fetchall()
 result[table]={"count":len(rows),"sha256":hashlib.sha256(json.dumps(rows,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()}
print(json.dumps(result))'''
    tables=json.loads(deployment.cluster.kubectl("exec","-n","breaker-banking","deployment/banking-store","--","python","-c",code,capture=True).stdout)
    pvc=deployment.cluster.get("persistentvolumeclaim","banking-data","-n","breaker-banking")
    key=deployment.cluster.get("secret","banking-key","-n","breaker-banking")
    return dict(schema_version="banking-history-proof-v1",tables=tables,pvc_uid=pvc["metadata"]["uid"],
        volume=pvc["spec"]["volumeName"],key_uid=key["metadata"]["uid"],key_material_sha256=hashlib.sha256(key["data"]["key"].encode()).hexdigest(),read_only=True)


def main():
    from src.banking_service.deploy import Deployment,DIRECTORY
    from src.banking_service.http import RuntimeClient
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--snapshot-history",action="store_true")
    p.add_argument("--reserve",type=Path,nargs=2,metavar=("QUALIFICATION_PLAN","REHEARSAL_PLAN"))
    p.add_argument("--output",type=Path,required=True);args=p.parse_args()
    if args.output.exists():p.error("output already exists")
    d=Deployment()
    if args.snapshot_history:result=history_snapshot(d)
    elif args.reserve:
        q,r=[json.loads(path.read_text()) for path in args.reserve]
        from src.benchmark.demo_qualification import binding
        if binding(q)!=binding(r) or r.get("rehearsal_of")!=q["namespace"]:raise ValueError("capacity_campaign_plans_differ")
        d.verify_deployment(json.loads((DIRECTORY/"deployment.json").read_text()));d.refresh_credentials()
        with d.forward("service/banking-store") as url:
            store=RuntimeClient(url,"Bearer "+(DIRECTORY/"runtime.token").read_text().strip())
            expected=digest(dict(qualification=digest(q),rehearsal=digest(r)))
            result=store.call("/reserve-capacity",dict(campaign_id=q["capacity"]["campaign_id"],binding=expected,requirements=q["capacity"]["requirements"]))
            validate_capacity(result,q,binding=expected,minimum_trials=42)
    else:p.error("select --snapshot-history or --reserve")
    private(args.output,result);print(args.output)


if __name__=="__main__":main()
