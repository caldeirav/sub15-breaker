"""Native-demo allocations over the same immutable v4 campaign history."""
import hashlib
import json
import re
import time

from src.benchmark.training_budget import TrainingBudget,POLICY
from src.benchmark.campaign_budget import LOCAL,EXTERNAL,usd
from src.infra.model_budget import atomic,encoded
from src.integrations.agentdojo.inventory import digest


class DemoBudget(TrainingBudget):
    def approve_review_extension(self,*,namespaces,reason):
        """Owner-approved additive eight-review allowance, restricted to fresh demo IDs."""
        if namespaces!=["nd7","nd8"] or not isinstance(reason,str) or not reason.strip():raise ValueError("review_extension_scope")
        with self.locked():
            entries=self.entries();self.baseline(entries);path=self.directory/"demo-review-extension-v1.json"
            if path.exists():return self.external_limit("nd7",entries=entries)
            if any(e["case_id"].split("-",1)[0] in namespaces for e in entries):raise RuntimeError("review_extension_already_spent")
            value=dict(schema_version="demo-review-extension-v1",parent_policy_sha256=digest(POLICY),namespaces=namespaces,
                additional_external=8,reason=reason,prefix_length=len(entries),prefix_sha256=digest(entries),global_caps_unchanged=True)
            self._exclusive(path,value)
            return POLICY["new_gemini_maximum"]+8

    def external_limit(self,namespace,*,entries=None):
        path=self.directory/"demo-review-extension-v1.json"
        if not path.exists():return POLICY["new_gemini_maximum"]
        value=json.loads(path.read_text());entries=self.entries() if entries is None else entries
        if (value.get("parent_policy_sha256")!=digest(POLICY) or value.get("namespaces")!=["nd7","nd8"] or value.get("additional_external")!=8 or
                value.get("global_caps_unchanged") is not True or digest(entries[:value["prefix_length"]])!=value["prefix_sha256"]):raise RuntimeError("review_extension_changed")
        return POLICY["new_gemini_maximum"]+(8 if namespace in value["namespaces"] else 0)

    def freeze_phase(self,plan):
        """Fresh nd2+ IDs; never replace nd1 or its consumed requests/reviews."""
        namespace=plan.get("namespace","")
        if not re.fullmatch(r"nd[1-9][0-9]*",namespace) or namespace=="nd1":raise ValueError("fresh_demo_namespace_required")
        if plan.get("policy_sha256")!=hashlib.sha256(encoded(POLICY)).hexdigest():raise ValueError("demo_policy_binding_required")
        for key in ("artifact_manifest_sha256","calibration_sha256","fixtures_sha256","code_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}",plan.get(key,"")):raise ValueError("demo_hash_binding_required")
        cases=plan.get("cases",[])
        if not cases or len({c["case_id"] for c in cases})!=len(cases):raise ValueError("demo_unique_cases_required")
        for case in cases:
            if not re.fullmatch(namespace+r"-[a-z0-9-]+",case["case_id"]):raise ValueError("demo_case_namespace")
            if case.get("task_id") not in {None,"user_task_0","user_task_2","user_task_13"}:raise ValueError("demo_task_scope")
            if case.get("gemini_data_generation",0):raise ValueError("demo_generation_not_authorized")
            for role in LOCAL|EXTERNAL:
                if type(case.get(role,0)) is not int or case.get(role,0)<0:raise ValueError("demo_invalid_allocation")
        local=sum(c.get(r,0) for c in cases for r in LOCAL);external=sum(c.get(r,0) for c in cases for r in EXTERNAL)
        if local>128 or external>17:raise ValueError("measurement_phase_allocation_cap")
        with self.locked():
            entries=self.entries();baseline=self.baseline(entries);path=self.directory/f"native-demo-{namespace}.json"
            if path.exists():
                if self.phase(namespace)!=plan:raise RuntimeError("demo_phase_changed")
                return
            if any(e["case_id"].startswith(namespace+"-") for e in entries):raise RuntimeError("phase_already_spent_before_freeze")
            issued=entries[baseline["prefix_length"]:]
            if (sum(e["role"] in LOCAL for e in entries)+local>POLICY["local_total"] or
                    sum(e["role"] in LOCAL for e in issued)+local>POLICY["new_local_maximum"]):raise ValueError("demo_local_cap")
            if (sum(e["role"] in EXTERNAL for e in entries)+external>POLICY["gemini_total"] or
                    sum(e["role"] in EXTERNAL for e in issued)+external>self.external_limit(namespace,entries=entries)):raise ValueError("demo_external_cap")
            if self.accounted(entries,baseline)+external*usd(POLICY["gemini_hold_per_operation_usd"])>usd(POLICY["gemini_cost_cap_usd"]):raise ValueError("demo_cost_envelope")
            self._exclusive(path,dict(plan=plan,sha256=digest(plan)))

    def phase(self,namespace):
        if not re.fullmatch(r"nd[1-9][0-9]*",namespace):raise ValueError("invalid_demo_namespace")
        value=json.loads((self.directory/f"native-demo-{namespace}.json").read_text())
        if value["sha256"]!=digest(value["plan"]):raise RuntimeError("demo_phase_changed")
        return value["plan"]

    def freeze_demo(self,plan):
        with self.locked():
            entries=self.entries();baseline=self.baseline(entries)
            path=self.directory/"native-demo-matrix-v1.json"
            if path.exists():
                if self.demo()!=plan:raise RuntimeError("demo_matrix_changed")
                return
            if plan.get("schema_version")!="native-demo-matrix-v1" or plan.get("policy_sha256")!=hashlib.sha256(encoded(POLICY)).hexdigest():raise ValueError("demo_policy_binding_required")
            for key in ("artifact_manifest_sha256","calibration_sha256","fixtures_sha256","code_sha256"):
                if not re.fullmatch(r"[0-9a-f]{64}",plan.get(key,"")):raise ValueError("demo_hash_binding_required")
            cases=plan.get("cases",[])
            if not cases or len({c["case_id"] for c in cases})!=len(cases):raise ValueError("demo_unique_cases_required")
            for case in cases:
                if not re.fullmatch(r"nd1-[a-z0-9-]+",case["case_id"]):raise ValueError("demo_case_namespace")
                for role in LOCAL|EXTERNAL:
                    if type(case.get(role,0)) is not int or case.get(role,0)<0:raise ValueError("demo_invalid_allocation")
                if case.get("gemini_data_generation",0):raise ValueError("demo_generation_not_authorized")
                if case.get("task_id") not in {"user_task_0","user_task_2","user_task_13",None}:raise ValueError("demo_task_scope")
                if case.get("task_id") is None and any(case.get(role,0) for role in LOCAL):raise ValueError("demo_local_task_required")
            ids={c["case_id"] for c in cases};outside=[e for e in entries[baseline["prefix_length"]:] if e["case_id"] not in ids]
            local=sum(c.get(r,0) for c in cases for r in LOCAL);external=sum(c.get(r,0) for c in cases for r in EXTERNAL)
            if local>120 or external>17:raise ValueError("demo_local_cap" if local>120 else "demo_external_cap")
            if baseline["local_spent"]+sum(e["role"] in LOCAL for e in outside)+local>POLICY["local_total"] or sum(e["role"] in LOCAL for e in outside)+local>POLICY["new_local_maximum"]:raise ValueError("demo_local_cap")
            if baseline["gemini_operations"]+sum(e["role"] in EXTERNAL for e in outside)+external>POLICY["gemini_total"] or sum(e["role"] in EXTERNAL for e in outside)+external>POLICY["new_gemini_maximum"]:raise ValueError("demo_external_cap")
            if self.accounted(entries,baseline)+external*usd(POLICY["gemini_hold_per_operation_usd"])>usd(POLICY["gemini_cost_cap_usd"]):raise ValueError("demo_cost_envelope")
            atomic(path,plan);atomic(self.directory/"native-demo-matrix-binding.json",dict(sha256=hashlib.sha256(encoded(plan)).hexdigest()))

    def original_demo(self):
        plan=json.loads((self.directory/"native-demo-matrix-v1.json").read_text())
        if json.loads((self.directory/"native-demo-matrix-binding.json").read_text())["sha256"]!=hashlib.sha256(encoded(plan)).hexdigest():raise RuntimeError("demo_matrix_changed")
        return plan

    def freeze_setup_correction(self,plan,*,failed_setup_run_id):
        """Additive binding only; retain all IDs, allocations and control evidence."""
        with self.locked():
            entries=self.entries();self.baseline(entries);parent=self.original_demo()
            if not re.fullmatch(r"[0-9a-f]{32}",failed_setup_run_id):raise ValueError("failed_setup_run_id_required")
            comparable=dict(plan,code_hashes=parent["code_hashes"],code_sha256=parent["code_sha256"])
            if comparable!=parent:raise ValueError("setup_correction_may_not_change_protocol_or_allocation")
            if set(plan["code_hashes"])!=set(parent["code_hashes"]):raise ValueError("setup_correction_code_scope")
            changed={name for name in parent["code_hashes"] if parent["code_hashes"][name]!=plan["code_hashes"].get(name)}
            if changed!={"src/benchmark/deployment.py","src/benchmark/demo.py","src/benchmark/demo_budget.py"}:raise ValueError("setup_correction_code_scope")
            if any(e["case_id"].startswith("nd1-") for e in entries):raise RuntimeError("setup_correction_requires_no_demo_inference_spent")
            controls={c["case_id"] for c in parent["cases"] if c["kind"]=="control"}
            started=[json.loads(path.read_text())["case_id"] for path in self.directory.glob("native-case-nd1-*.json")]
            if any(case_id not in controls for case_id in started):
                raise RuntimeError("setup_correction_requires_unstarted_learned_cases")
            effective=dict(plan,setup_correction=dict(parent_matrix_sha256=digest(parent),
                failed_setup_run_id=failed_setup_run_id,changed_code=sorted(changed),reason="kubectl restore regenerated last-applied annotation; use resourceVersion/UID-tested JSON patches",
                repeated_cases=[],allocation_changed=False,controls_inherited=True))
            value=dict(plan=effective,sha256=hashlib.sha256(encoded(effective)).hexdigest())
            path=self.directory/"native-demo-setup-correction-v1.json"
            if path.exists():
                if json.loads(path.read_text())!=value:raise RuntimeError("setup_correction_changed")
            else:self._exclusive(path,value)
            return effective

    def demo(self):
        parent=self.original_demo();path=self.directory/"native-demo-setup-correction-v1.json"
        if not path.exists():return parent
        value=json.loads(path.read_text());plan=value["plan"]
        if (hashlib.sha256(encoded(plan)).hexdigest()!=value["sha256"] or
                plan["setup_correction"]["parent_matrix_sha256"]!=digest(parent)):raise RuntimeError("setup_correction_changed")
        return plan

    def reserve(self,*,role,case_id,trace_id,request=None,model=None):
        namespace=case_id.split("-",1)[0]
        if not re.fullmatch(r"nd[1-9][0-9]*",namespace):return super().reserve(role=role,case_id=case_id,trace_id=trace_id,request=request,model=model)
        with self.locked():
            entries=self.entries();baseline=self.baseline(entries);plan=self.demo() if namespace=="nd1" else self.phase(namespace);issued=entries[baseline["prefix_length"]:]
            case=next((c for c in plan["cases"] if c["case_id"]==case_id),None)
            if case is None or role not in LOCAL|EXTERNAL:raise RuntimeError("undeclared_demo_request")
            if sum(e["case_id"]==case_id and e["role"]==role for e in issued)>=case.get(role,0):raise RuntimeError("demo_case_budget_exhausted")
            if role in LOCAL:
                if sum(e["role"] in LOCAL for e in entries)>=POLICY["local_total"] or sum(e["role"] in LOCAL for e in issued)>=POLICY["new_local_maximum"]:raise RuntimeError("demo_local_exhausted")
                if model!=plan["acting_model"]:raise RuntimeError("demo_local_model_binding")
                hold=usd(0)
            else:
                if model!=POLICY["gemini_model"]:raise RuntimeError("demo_external_model_binding")
                if sum(e["role"] in EXTERNAL for e in entries)>=POLICY["gemini_total"] or sum(e["role"] in EXTERNAL for e in issued)>=self.external_limit(namespace,entries=entries):raise RuntimeError("demo_external_exhausted")
                hold=usd(POLICY["gemini_hold_per_operation_usd"])
            if self.accounted(entries,baseline)+hold>usd(POLICY["gemini_cost_cap_usd"]):raise RuntimeError("demo_cost_exhausted")
            value=dict(sequence=len(entries)+1,role=role,case_id=case_id,phase=plan.get("phase","native_demo_validation"),trace_id=trace_id,model=model,
                policy_version=POLICY["version"],cost_hold_usd=str(hold),spent=True,reserved_at=time.time(),request_sha256=hashlib.sha256(encoded(request)).hexdigest())
            self._exclusive(self.directory/f"attempt-{value['sequence']:04d}.json",value);return value
