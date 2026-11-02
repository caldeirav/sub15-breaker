"""Explicit OFFLINE browser fixture. Never imports/constructs the real runtime."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import threading
import time

import uvicorn

from src.demo_ui.app import create_app
from src.demo_ui.state import Controller
from src.demo_ui.allocation import CARDS

TOKEN="offline-browser-fixture-token-not-a-platform-credential"


def plan():
    slots=[];cases=[]
    for i,card in enumerate(CARDS):
        slot="ui1-"+card.lower()+"-1"
        slots.append(dict(slot=slot,card=card,order=["classifier","llm"] if i%2==0 else ["llm","classifier"]))
        for arm in ("classifier","llm"):
            cases.append(dict(case_id=slot+"-"+arm,slot=slot,card_id=card,arm=arm,kind="card",actor=0,llm_guard=0))
        cases.append(dict(case_id=slot+"-review",slot=slot,kind="external_review",gemini_harness_judge=1))
    return dict(namespace="ui1",slots=slots,cases=cases,fixture=True)


class Budget:
    def __init__(self,directory):self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True);self.lock=threading.RLock()
    def plan(self,**kwargs):return plan()
    @contextmanager
    def locked(self):
        with self.lock:yield
    @staticmethod
    def _exclusive(path,value):
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"w") as stream:json.dump(value,stream)


class FixtureRuntime:
    def __init__(self,*args):self.calls=[];self.opened=False;self.closed=False
    def open(self,job):
        self.opened=True;job.emit("startup",dict(stage="fixture_startup",phase="finished"))
    def run_lane(self,job,arm,spec):
        self.calls.append((spec["card_id"],arm))
        fault=spec["card_id"] in {"D04","D05"}
        job.emit(arm,dict(stage="agent",phase="thinking",attempt=1))
        time.sleep(.05)
        job.emit(arm,dict(stage="guard_review",phase="started",tool="send_money"))
        time.sleep(.05)
        job.emit(arm,dict(stage="guard_review",phase="finished",decision="error" if fault else "block" if spec["card_id"]=="D02" else "allow",duration_ns=10000000))
        summary=dict(arm=arm,fault_control=fault,producer="offline_fixture",status="error" if fault else "completed",
            golden_pass=True,expected="error" if fault else "block" if spec["card_id"]=="D02" else "allow",
            observed="error" if fault else "block" if spec["card_id"]=="D02" else "allow",utility=not fault,
            effects_verified=True,telemetry="fixture",cleanup_ok=True,trace_id="fixture-not-a-live-trace",run_id="fixture",
            experiment_id="5",final_answer="Explicit offline UI fixture. No real model, gateway or tools invoked.",
            timing=dict(guard_whole_review=None if fault else dict(count=1,total_ms=10,median_ms=10),
                        classifier_core=dict(count=1,total_ms=5,median_ms=5) if arm=="classifier" and not fault else None))
        return dict(case_id=spec["case_id"]),summary
    def review(self,job,slot,records):
        return dict(verdict="offline_fixture",operations=0,task_agreements=0,task_errors=0)
    def close(self):self.closed=True


class FixtureController(Controller):
    def status(self):return dict(super().status(),fixture=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--directory",type=Path,required=True);parser.add_argument("--port",type=int,default=8092)
    args=parser.parse_args()
    args.directory.mkdir(parents=True,exist_ok=False)
    controller=FixtureController(Budget(args.directory/"budget"),args.directory/"jobs",FixtureRuntime)
    uvicorn.run(create_app(controller,TOKEN,port=args.port),host="127.0.0.1",port=args.port,access_log=False)


if __name__=="__main__":main()
