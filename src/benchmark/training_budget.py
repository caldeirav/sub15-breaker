"""Owner-approved v2 envelope over the existing campaign ledger, never a reset."""
import hashlib
import json
import time
import argparse
from pathlib import Path

from src.benchmark.campaign_budget import CampaignBudget,POLICY as PARENT,LOCAL,EXTERNAL,usd
from src.infra.model_budget import encoded,atomic

POLICY=dict(version="banking-training-campaign-v4",parent_policy_sha256=hashlib.sha256(encoded(PARENT)).hexdigest(),
    local_total=2048,gemini_total=512,gemini_cost_cap_usd="100.00",gemini_hold_per_operation_usd="0.50",
    gemini_model=PARENT["gemini_model"],new_local_maximum=768,new_gemini_maximum=128,
    prompt_pilot_maximum=12,retries=0,fallback=False,original_corpus_fit=False,
    goal_paraphrases="pending-human-semantic-fidelity-review",fresh_challenge=True,
    validation_false_block_constraints=["overall<=0.10","reads<=0.10","mutations<=0.10"])


class TrainingBudget(CampaignBudget):
    def freeze(self):
        with self.locked():
            entries=self.entries()
            if (self.directory/"policy-v4.json").exists():self.baseline(entries);return
            parent=self._baseline(entries)
            if len(entries)!=len({entry["sequence"] for entry in entries}):raise RuntimeError("duplicate_ledger_sequence")
            baseline=dict(prefix_length=len(entries),prefix_sha256=hashlib.sha256(encoded(entries)).hexdigest(),
                local_spent=sum(e["role"] in LOCAL for e in entries),gemini_operations=sum(e["role"] in EXTERNAL for e in entries),
                prior_accounted_cost_plus_holds_usd=str(self._accounted(entries,parent)),
                prior_settlements_sha256=self._settlements_hash(len(entries)))
            if baseline["local_spent"]+POLICY["new_local_maximum"]>POLICY["local_total"]:raise ValueError("v2_local_envelope_exceeds_total")
            if baseline["gemini_operations"]+POLICY["new_gemini_maximum"]>POLICY["gemini_total"]:raise ValueError("v2_gemini_envelope_exceeds_total")
            if usd(baseline["prior_accounted_cost_plus_holds_usd"])+POLICY["new_gemini_maximum"]*usd(POLICY["gemini_hold_per_operation_usd"])>usd(POLICY["gemini_cost_cap_usd"]):
                raise ValueError("v2_worst_case_holds_exceed_total")
            if (self.directory/"training-v2-baseline.json").exists():raise RuntimeError("v2_freeze_incomplete")
            atomic(self.directory/"training-v2-baseline.json",baseline)
            atomic(self.directory/"policy-v4.json",POLICY)

    def _settlements_hash(self,length):
        values={path.name:json.loads(path.read_text()) for path in sorted(self.directory.glob("settlement-*.json"))
            if int(path.stem.split("-")[1])<=length}
        return hashlib.sha256(encoded(values)).hexdigest()

    def baseline(self,entries):
        if json.loads((self.directory/"policy-v4.json").read_text())!=POLICY:raise RuntimeError("v2_policy_changed")
        baseline=json.loads((self.directory/"training-v2-baseline.json").read_text());prefix=entries[:baseline["prefix_length"]]
        if len(prefix)!=baseline["prefix_length"] or hashlib.sha256(encoded(prefix)).hexdigest()!=baseline["prefix_sha256"]:
            raise RuntimeError("v2_historical_ledger_changed")
        parent=self._baseline(prefix)
        if (baseline["prior_settlements_sha256"]!=self._settlements_hash(len(prefix)) or
                baseline["local_spent"]!=sum(e["role"] in LOCAL for e in prefix) or
                baseline["gemini_operations"]!=sum(e["role"] in EXTERNAL for e in prefix) or
                usd(baseline["prior_accounted_cost_plus_holds_usd"])!=self._accounted(prefix,parent)):
            raise RuntimeError("v2_historical_accounting_changed")
        if any(e.get("policy_version")!=POLICY["version"] for e in entries[len(prefix):]):raise RuntimeError("v2_unexpected_policy")
        return baseline

    def freeze_pilot(self,plan):
        with self.locked():
            self.baseline(self.entries())
            if plan.get("schema_version")!="banking-v2-prompt-pilot-v1" or plan.get("policy_sha256")!=hashlib.sha256(encoded(POLICY)).hexdigest():
                raise ValueError("v2_pilot_policy_binding_required")
            for key in ("protocol_sha256","audit_sha256","source_decision_sha256"):
                value=plan.get(key)
                if not isinstance(value,str) or len(value)!=64 or any(c not in "0123456789abcdef" for c in value):raise ValueError("v2_pilot_hash_required")
            cases=plan.get("cases",[])
            if len(cases)!=POLICY["prompt_pilot_maximum"] or len({case["case_id"] for case in cases})!=len(cases):raise ValueError("v2_pilot_cases_required")
            path=self.directory/"v2-prompt-pilot.json"
            if path.exists():
                if json.loads(path.read_text())!=plan:raise RuntimeError("v2_pilot_changed")
                self.pilot()
            else:
                atomic(path,plan);atomic(self.directory/"v2-prompt-pilot-binding.json",dict(sha256=hashlib.sha256(encoded(plan)).hexdigest()))

    def pilot(self):
        plan=json.loads((self.directory/"v2-prompt-pilot.json").read_text())
        if json.loads((self.directory/"v2-prompt-pilot-binding.json").read_text())["sha256"]!=hashlib.sha256(encoded(plan)).hexdigest():
            raise RuntimeError("v2_pilot_changed")
        return plan

    def freeze_diagnostics(self,plan):
        with self.locked():
            self.baseline(self.entries())
            if (plan.get("schema_version")!="banking-v2-api-diagnostic-v1" or
                    plan.get("parent_pilot_sha256")!=hashlib.sha256(encoded(self.pilot())).hexdigest() or
                    plan.get("policy_sha256")!=hashlib.sha256(encoded(POLICY)).hexdigest()):
                raise ValueError("v2_diagnostic_binding_required")
            if [case.get("case_id") for case in plan.get("cases",[])]!=["v2-api-diagnostic-minimal","v2-api-diagnostic-original-schema"]:
                raise ValueError("v2_two_named_diagnostics_required")
            path=self.directory/"v2-api-diagnostic.json"
            if path.exists():
                if json.loads(path.read_text())!=plan:raise RuntimeError("v2_diagnostic_changed")
                self.diagnostics()
            else:
                atomic(path,plan);atomic(self.directory/"v2-api-diagnostic-binding.json",dict(sha256=hashlib.sha256(encoded(plan)).hexdigest()))

    def diagnostics(self):
        plan=json.loads((self.directory/"v2-api-diagnostic.json").read_text())
        if json.loads((self.directory/"v2-api-diagnostic-binding.json").read_text())["sha256"]!=hashlib.sha256(encoded(plan)).hexdigest():
            raise RuntimeError("v2_diagnostic_changed")
        return plan

    def freeze_corrected_pilot(self,plan):
        with self.locked():
            self.baseline(self.entries());parent=self.pilot()
            if (plan.get("schema_version")!="banking-v2-prompt-pilot-v2" or
                    plan.get("parent_pilot_sha256")!=hashlib.sha256(encoded(parent)).hexdigest() or
                    plan.get("policy_sha256")!=hashlib.sha256(encoded(POLICY)).hexdigest()):
                raise ValueError("v2_corrected_pilot_binding_required")
            expected=[case["case_id"].replace("v2-pilot-","v2-wire-pilot-",1) for case in parent["cases"]]
            if [case["case_id"] for case in plan.get("cases",[])]!=expected:raise ValueError("v2_corrected_pilot_cases_changed")
            for key in ("audit_sha256","source_decision_sha256"):
                if plan.get(key)!=parent[key]:raise ValueError("v2_corrected_pilot_sources_changed")
            if not plan.get("protocol",{}).get("wire_schemas"):raise ValueError("v2_corrected_wire_binding_required")
            path=self.directory/"v2-prompt-pilot-corrected.json"
            if path.exists():
                if json.loads(path.read_text())!=plan:raise RuntimeError("v2_corrected_pilot_changed")
                self.corrected_pilot()
            else:
                atomic(path,plan);atomic(self.directory/"v2-prompt-pilot-corrected-binding.json",dict(sha256=hashlib.sha256(encoded(plan)).hexdigest()))

    def corrected_pilot(self):
        plan=json.loads((self.directory/"v2-prompt-pilot-corrected.json").read_text())
        if json.loads((self.directory/"v2-prompt-pilot-corrected-binding.json").read_text())["sha256"]!=hashlib.sha256(encoded(plan)).hexdigest():
            raise RuntimeError("v2_corrected_pilot_changed")
        return plan

    def accounted(self,entries,baseline):
        total=usd(baseline["prior_accounted_cost_plus_holds_usd"])
        for entry in entries[baseline["prefix_length"]:]:
            if entry["role"] not in EXTERNAL:continue
            cost=usd(entry["cost_hold_usd"]);path=self.directory/f"settlement-{entry['sequence']:04d}.json"
            if path.exists():
                settlement=json.loads(path.read_text())
                if settlement.get("sequence")!=entry["sequence"]:raise RuntimeError("v2_settlement_mismatch")
                if settlement.get("usage_verified"):cost=usd(settlement["accounted_cost_usd"])
            total+=cost
        return total

    def reserve(self,*,role,case_id,trace_id,request=None,model=None):
        with self.locked():
            entries=self.entries();baseline=self.baseline(entries);plan=self.pilot();phase="v2_prompt_pilot"
            if case_id.startswith("v2-api-diagnostic-"):
                plan=self.diagnostics();phase="v2_api_diagnostic"
            elif case_id.startswith("v2-wire-pilot-"):
                plan=self.corrected_pilot();phase="v2_prompt_pilot_corrected"
            if role!="gemini_data_generation" or model!=POLICY["gemini_model"]:raise RuntimeError("v2_pilot_role_or_model_not_authorized")
            if case_id not in {case["case_id"] for case in plan["cases"]}:raise RuntimeError("v2_undeclared_pilot_case")
            issued=entries[baseline["prefix_length"]:]
            if any(e["case_id"]==case_id for e in issued):raise RuntimeError("v2_case_already_spent")
            if sum(e["role"] in EXTERNAL for e in entries)>=POLICY["gemini_total"] or sum(e["role"] in EXTERNAL for e in issued)>=POLICY["new_gemini_maximum"]:
                raise RuntimeError("v2_gemini_budget_exhausted")
            hold=usd(POLICY["gemini_hold_per_operation_usd"])
            if self.accounted(entries,baseline)+hold>usd(POLICY["gemini_cost_cap_usd"]):raise RuntimeError("v2_cost_cap_reached")
            entry=dict(sequence=len(entries)+1,role=role,case_id=case_id,trace_id=trace_id,phase=phase,
                model=model,policy_version=POLICY["version"],cost_hold_usd=str(hold),spent=True,reserved_at=time.time(),
                request_sha256=hashlib.sha256(encoded(request)).hexdigest())
            self._exclusive(self.directory/f"attempt-{entry['sequence']:04d}.json",entry);return entry

    def settle(self,sequence,*,accounted_cost_usd=None,usage_verified=False):
        if type(usage_verified) is not bool:raise ValueError("verified_usage_flag_required")
        with self.locked():
            entries=self.entries();baseline=self.baseline(entries)
            if type(sequence) is not int or not baseline["prefix_length"]<sequence<=len(entries):raise ValueError("unknown_v2_attempt")
            entry=entries[sequence-1]
            if entry["role"] not in EXTERNAL:raise ValueError("not_external_operation")
            self._exclusive(self.directory/f"settlement-{sequence:04d}.json",dict(sequence=sequence,usage_verified=usage_verified,
                accounted_cost_usd=str(usd(accounted_cost_usd)) if usage_verified else None,held_if_unknown_usd=entry["cost_hold_usd"],recorded_at=time.time()))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory",type=Path,required=True);parser.add_argument("--freeze",action="store_true")
    args=parser.parse_args();budget=TrainingBudget(args.directory)
    if args.freeze:budget.freeze()
    with budget.locked():
        entries=budget.entries();baseline=budget.baseline(entries)
        print(json.dumps(dict(policy=POLICY,local_spent=sum(e["role"] in LOCAL for e in entries),
            gemini_operations=sum(e["role"] in EXTERNAL for e in entries),accounted_cost_plus_holds_usd=str(budget.accounted(entries,baseline)),
            historical_prefix_length=baseline["prefix_length"],new_local_spent=sum(e["role"] in LOCAL for e in entries[baseline["prefix_length"]:]),
            new_gemini_operations=sum(e["role"] in EXTERNAL for e in entries[baseline["prefix_length"]:])),indent=2))


if __name__=="__main__":main()
