"""Owner-approved cumulative campaign budget; matrix approval precedes dispatch.

Older policies/entries are retained. Monetary accounting uses conservative USD
holds, not an invoice guarantee. Missing usage never releases a hold as zero.
"""
from contextlib import contextmanager
import argparse
from decimal import Decimal,InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import time

from src.benchmark.budget import PILOT,EXTENDED_PILOT
from src.infra.model_budget import atomic,encoded

POLICY=dict(version="banking-guard-campaign-v3",local_total=2048,gemini_total=512,
    gemini_cost_cap_usd="50.00",gemini_hold_per_operation_usd="0.50",gemini_model="gemini:/gemini-2.5-flash",
    phases={"guard_canary":32,"paired_replay":256,"episodes":1008,"diagnostics":256},
    validation_objective=dict(minimize="false_allows",maximum_observed_false_block_rate="0.10"),
    live_tasks=["user_task_0","user_task_2","user_task_13"],offline_groups="existing-pinned-banking-only",
    retries=0,fallback=False,supersedes=EXTENDED_PILOT["version"],
    prior_policy_sha256=hashlib.sha256(encoded(EXTENDED_PILOT)).hexdigest())
LOCAL={"actor","llm_guard"}
EXTERNAL={"gemini_task_judge","gemini_harness_judge","gemini_data_generation"}


def usd(value):
    try:number=Decimal(str(value))
    except (InvalidOperation,ValueError):raise ValueError("invalid_cost") from None
    if not number.is_finite() or number<0:raise ValueError("invalid_cost")
    return number


class CampaignBudget:
    def __init__(self,directory):self.directory=Path(directory)

    @contextmanager
    def locked(self):
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(self.directory/".lock",os.O_CREAT|os.O_RDWR,0o600)
        with os.fdopen(fd,"w") as stream:
            fcntl.flock(stream,fcntl.LOCK_EX)
            yield

    def entries(self):
        values=[json.loads(path.read_text()) for path in sorted(self.directory.glob("attempt-*.json"))]
        if [v["sequence"] for v in values]!=list(range(1,len(values)+1)):raise RuntimeError("campaign_ledger_gap")
        return values

    def freeze(self):
        with self.locked():
            for filename,expected in (("policy.json",PILOT),("policy-v2.json",EXTENDED_PILOT)):
                if json.loads((self.directory/filename).read_text())!=expected:raise RuntimeError("campaign_predecessor_changed")
            path=self.directory/"policy-v3.json"
            entries=self.entries()
            if path.exists():
                if json.loads(path.read_text())!=POLICY:raise RuntimeError("campaign_policy_changed")
                self._baseline(entries)
                return
            if (self.directory/"campaign-baseline.json").exists():raise RuntimeError("campaign_freeze_incomplete")
            if any(e.get("policy_version")==POLICY["version"] for e in entries):raise RuntimeError("campaign_policy_missing")
            external=sum(e["role"] in EXTERNAL for e in entries)
            baseline=dict(ledger_prefix_length=len(entries),ledger_prefix_sha256=hashlib.sha256(encoded(entries)).hexdigest(),
                local_spent=sum(e["role"] in LOCAL for e in entries),external_operations=external,
                historical_external_hold_usd=str(external*usd(POLICY["gemini_hold_per_operation_usd"])),
                historical_provider_HTTP_attempts="unknown",historical_holds_released=False,
                note="Conservative envelope for all recorded historical Gemini operations, including unknown usage and late reconciliation; not a measured bill.")
            if baseline["local_spent"]>POLICY["local_total"] or external>POLICY["gemini_total"]:
                raise RuntimeError("campaign_already_exhausted")
            if usd(baseline["historical_external_hold_usd"])>usd(POLICY["gemini_cost_cap_usd"]):raise RuntimeError("campaign_cost_exhausted")
            atomic(self.directory/"campaign-baseline.json",baseline)
            atomic(path,POLICY)

    def _baseline(self,entries):
        if json.loads((self.directory/"policy-v3.json").read_text())!=POLICY:raise RuntimeError("campaign_policy_changed")
        baseline=json.loads((self.directory/"campaign-baseline.json").read_text())
        prefix=entries[:baseline["ledger_prefix_length"]]
        if len(prefix)!=baseline["ledger_prefix_length"] or hashlib.sha256(encoded(prefix)).hexdigest()!=baseline["ledger_prefix_sha256"]:
            raise RuntimeError("historical_ledger_changed")
        external=sum(e["role"] in EXTERNAL for e in prefix)
        if (baseline["local_spent"]!=sum(e["role"] in LOCAL for e in prefix) or baseline["external_operations"]!=external or
                usd(baseline["historical_external_hold_usd"])!=external*usd(POLICY["gemini_hold_per_operation_usd"])):
            raise RuntimeError("campaign_baseline_changed")
        if any(entry.get("policy_version")!=POLICY["version"] for entry in entries[baseline["ledger_prefix_length"]:]):
            raise RuntimeError("unexpected_post_extension_policy_requires_reconciliation")
        return baseline

    def freeze_matrix(self,matrix):
        """Call after input/data/artifact gates, not merely to unlock more calls."""
        with self.locked():
            self._baseline(self.entries())
            for key in ("policy_id","input_version","dataset_manifest_sha256","artifact_manifest_sha256"):
                if not isinstance(matrix.get(key),str) or not matrix[key]:raise ValueError("matrix_binding_required")
            for key in ("dataset_manifest_sha256","artifact_manifest_sha256"):
                if not re.fullmatch(r"[0-9a-f]{64}",matrix[key]):raise ValueError("matrix_hash_required")
            cases=matrix.get("cases",[])
            if not cases or len({c["case_id"] for c in cases})!=len(cases):raise ValueError("matrix_cases_required")
            phases={name:0 for name in POLICY["phases"]}
            for case in cases:
                if not isinstance(case["case_id"],str) or not case["case_id"]:raise ValueError("invalid_case_id")
                if case.get("phase") not in phases:raise ValueError("undeclared_campaign_scope")
                for role in LOCAL|EXTERNAL:
                    count=case.get(role,0)
                    if type(count) is not int or count<0:raise ValueError("invalid_case_budget")
                if case.get("task_id") not in POLICY["live_tasks"]:
                    if case.get("task_id") is not None or any(case.get(role,0) for role in LOCAL):raise ValueError("undeclared_campaign_scope")
                phases[case["phase"]]+=sum(case.get(role,0) for role in LOCAL)
            if any(count>POLICY["phases"][name] for name,count in phases.items()):raise ValueError("phase_allocation_exceeds_ceiling")
            entries=self.entries();self._baseline(entries)
            # Generation is a separate pre-training plan, but consumes the same
            # cumulative totals. Do not reset it to the historical baseline.
            matrix_ids={case["case_id"] for case in cases}
            outside=[entry for entry in entries if entry.get("case_id") not in matrix_ids or entry.get("policy_version")!=POLICY["version"]]
            if sum(phases.values())+sum(e["role"] in LOCAL for e in outside)>POLICY["local_total"]:raise ValueError("matrix_exceeds_total")
            if sum(c.get(r,0) for c in cases for r in EXTERNAL)+sum(e["role"] in EXTERNAL for e in outside)>POLICY["gemini_total"]:
                raise ValueError("matrix_exceeds_gemini_total")
            path=self.directory/"matrix-v3.json"
            if path.exists():
                if json.loads(path.read_text())!=matrix:raise RuntimeError("campaign_matrix_changed")
                self._matrix()
            else:
                atomic(path,matrix)
                atomic(self.directory/"matrix-v3-binding.json",dict(sha256=hashlib.sha256(encoded(matrix)).hexdigest()))

    def _matrix(self):
        matrix=json.loads((self.directory/"matrix-v3.json").read_text())
        binding=json.loads((self.directory/"matrix-v3-binding.json").read_text())
        if binding.get("sha256")!=hashlib.sha256(encoded(matrix)).hexdigest():raise RuntimeError("campaign_matrix_changed")
        return matrix

    def freeze_generation_plan(self,plan):
        """A pre-training scope extension, not a fabricated model-artifact gate."""
        with self.locked():
            entries=self.entries();self._baseline(entries)
            if plan.get("schema_version")!="banking-hybrid-generation-plan-v1" or plan.get("parent_policy_sha256")!=hashlib.sha256(encoded(POLICY)).hexdigest():
                raise ValueError("generation_parent_policy_required")
            for key in ("review_decision_sha256","source_dataset_sha256","generator_protocol_sha256","split_recipe_sha256"):
                if not isinstance(plan.get(key),str) or not re.fullmatch(r"[0-9a-f]{64}",plan[key]):raise ValueError("generation_binding_required")
            if plan.get("model")!=POLICY["gemini_model"]:raise ValueError("generation_model_profile_mismatch")
            cases=plan.get("cases",[])
            if not cases or len({c["case_id"] for c in cases})!=len(cases):raise ValueError("generation_cases_required")
            for case in cases:
                if (not isinstance(case["case_id"],str) or not case["case_id"] or case.get("task_id") is not None or
                        case.get("phase")!="data_generation" or type(case.get("gemini_data_generation")) is not int or case["gemini_data_generation"]!=1):
                    raise ValueError("generation_case_scope_invalid")
            if len(cases)+sum(e["role"] in EXTERNAL for e in entries)>POLICY["gemini_total"]:raise ValueError("generation_exceeds_total")
            path=self.directory/"generation-plan-v1.json"
            if path.exists():
                if json.loads(path.read_text())!=plan:raise RuntimeError("generation_plan_changed")
                self._generation_plan()
            else:
                atomic(path,plan);atomic(self.directory/"generation-plan-binding.json",dict(sha256=hashlib.sha256(encoded(plan)).hexdigest()))

    def _generation_plan(self):
        plan=json.loads((self.directory/"generation-plan-v1.json").read_text())
        binding=json.loads((self.directory/"generation-plan-binding.json").read_text())
        if binding["sha256"]!=hashlib.sha256(encoded(plan)).hexdigest():raise RuntimeError("generation_plan_changed")
        return plan

    def _accounted(self,entries,baseline):
        total=usd(baseline["historical_external_hold_usd"])
        for entry in entries[baseline["ledger_prefix_length"]:]:
            if entry["role"] not in EXTERNAL:continue
            cost=usd(entry["cost_hold_usd"])
            outcome=self.directory/f"settlement-{entry['sequence']:04d}.json"
            if outcome.exists():
                value=json.loads(outcome.read_text())
                if value.get("sequence")!=entry["sequence"]:raise RuntimeError("cost_settlement_mismatch")
                if value.get("usage_verified"):
                    settled=usd(value["accounted_cost_usd"])
                    # An overrun must consume its real amount, not be clamped.
                    cost=settled
            total+=cost
        return total

    def reserve(self,*,role,case_id,trace_id,request=None,model=None):
        with self.locked():
            entries=self.entries();baseline=self._baseline(entries)
            if role=="gemini_data_generation":
                if not (self.directory/"generation-plan-v1.json").exists():raise RuntimeError("generation_plan_not_frozen")
                matrix=self._generation_plan()
            else:
                matrix_path=self.directory/"matrix-v3.json"
                if not matrix_path.exists():raise RuntimeError("reviewed_campaign_matrix_not_frozen")
                matrix=self._matrix()
            case=next((c for c in matrix["cases"] if c["case_id"]==case_id),None)
            if case is None or role not in LOCAL|EXTERNAL:raise RuntimeError("undeclared_campaign_attempt")
            issued=entries[baseline["ledger_prefix_length"]:]
            if sum(e["case_id"]==case_id and e["role"]==role for e in issued)>=case.get(role,0):raise RuntimeError("case_budget_exhausted")
            hold=Decimal(0)
            if role in LOCAL:
                if sum(e["role"] in LOCAL for e in entries)>=POLICY["local_total"]:raise RuntimeError("local_budget_exhausted")
                if sum(e["role"] in LOCAL and e.get("phase")==case["phase"] for e in issued)>=POLICY["phases"][case["phase"]]:
                    raise RuntimeError("phase_budget_exhausted")
            else:
                if model!=POLICY["gemini_model"]:raise RuntimeError("unapproved_gemini_cost_profile")
                if sum(e["role"] in EXTERNAL for e in entries)>=POLICY["gemini_total"]:raise RuntimeError("gemini_budget_exhausted")
                hold=usd(POLICY["gemini_hold_per_operation_usd"])
            if self._accounted(entries,baseline)+hold>usd(POLICY["gemini_cost_cap_usd"]):raise RuntimeError("gemini_cost_cap_reached")
            entry=dict(sequence=len(entries)+1,role=role,case_id=case_id,phase=case["phase"],trace_id=trace_id,
                request_sha256=hashlib.sha256(encoded(request)).hexdigest(),reserved_at=time.time(),spent=True,
                policy_version=POLICY["version"],cost_hold_usd=str(hold),model=model)
            self._exclusive(self.directory/f"attempt-{entry['sequence']:04d}.json",entry)
            return entry

    def settle(self,sequence,*,accounted_cost_usd=None,usage_verified=False):
        if type(usage_verified) is not bool:raise ValueError("verified_usage_flag_required")
        with self.locked():
            entries=self.entries();baseline=self._baseline(entries)
            if type(sequence) is not int or not baseline["ledger_prefix_length"]<sequence<=len(entries):raise ValueError("unknown_campaign_attempt")
            entry=entries[sequence-1]
            if entry["role"] not in EXTERNAL:raise ValueError("not_external_operation")
            cost=str(usd(accounted_cost_usd)) if usage_verified else None
            result=dict(sequence=sequence,usage_verified=bool(usage_verified),accounted_cost_usd=cost,
                held_if_unknown_usd=entry["cost_hold_usd"],recorded_at=time.time())
            self._exclusive(self.directory/f"settlement-{sequence:04d}.json",result)

    @staticmethod
    def _exclusive(path,value):
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"wb") as output:
            output.write(encoded(value));output.flush();os.fsync(output.fileno())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory",type=Path,required=True,help="Existing cumulative ledger directory; never a replacement budget")
    parser.add_argument("--freeze",action="store_true",help="Freeze approved v3 ceilings while preserving the complete historical prefix")
    args=parser.parse_args()
    budget=CampaignBudget(args.directory)
    if args.freeze:budget.freeze()
    with budget.locked():
        entries=budget.entries();baseline=budget._baseline(entries)
        print(json.dumps(dict(policy=POLICY,local_spent=sum(e["role"] in LOCAL for e in entries),
            external_operations_recorded=sum(e["role"] in EXTERNAL for e in entries),
            accounted_cost_plus_holds_usd=str(budget._accounted(entries,baseline)),
            historical_baseline=baseline,matrix_frozen=(args.directory/"matrix-v3.json").exists()),indent=2))


if __name__=="__main__":main()
