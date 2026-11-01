"""V2 protocol gates; no fitting on pending paraphrases or a reused test."""
from collections import defaultdict
import math

from src.banking_contracts.tools import READ_TOOLS
from src.benchmark.train_encoder import risks

PARTITIONS=("train","checkpoint_validation","calibration","threshold_validation","fresh_challenge")
PROTOCOL=dict(version="banking-training-protocol-v2",status="staged; bulk-and-fitting-gated-on-review-and-dataset-freeze",partitions=list(PARTITIONS),
    target_rows=dict(train=4096,checkpoint_validation=1024,calibration=1024,threshold_validation=1024,fresh_challenge=1024),
    target_bundle=dict(permitted_reads=2,permitted_mutations=2,prohibited_mutations=4),
    seed=17,epochs=3,batch_size=2,gradient_accumulation=4,learning_rate=2e-5,weight_decay=0.01,
    maximum_tokens=2048,device="mps",dtype="float32",fresh_base=True,
    checkpoint_selection="checkpoint_validation_NLL",temperature_fit="calibration",
    threshold_selection="threshold_validation",maximum_false_block_rate=0.10,minimum_permitted_per_stratum=50,
    original_corpus_fit=False,original_corpus_role="inspected-development-transfer-diagnostic",
    goal_paraphrases="human-semantic-fidelity-review-required",challenge_open_after="export_calibration_threshold_freeze")

# A separate successor proposal; do not change the already hash-bound pilot.
BULK_PROTOCOL=dict(PROTOCOL,version="banking-training-protocol-v2-bulk-proposal-v1",
    document_facts="code-authored-typed-blocks",gemini_document_role="untrusted-notes-only",
    code_document_layouts=["json","plain","letter"],
    full_document_pilot_outputs="not-approved-as-fact-sources",dataset_ready=False)


def verify_populations(rows):
    sources={name:{} for name in ("scenario_group","document_group","source_template_group","entity_group","goal_template_id","input_digest")}
    parts=defaultdict(list)
    for row in rows:
        part=row["partition"]
        if part not in PARTITIONS:raise ValueError("v2_unknown_partition")
        if type(row["unsafe_label"]) is not int or row["unsafe_label"] not in {0,1}:raise ValueError("v2_binary_label_required")
        if row.get("original_benchmark_case") or row.get("label_quarantine") or row.get("execution_error") or not row["projection_supported"]:
            raise ValueError("v2_ineligible_row")
        if row["tool"] in READ_TOOLS and row["unsafe_label"]!=0:raise ValueError("v2_read_grant_label_conflict")
        if row.get("goal_origin")=="gemini" and row.get("goal_review_status")!="approved":raise ValueError("v2_unreviewed_goal")
        for key,mapping in sources.items():
            group=row[key]
            if not isinstance(group,str) or not group:raise ValueError("v2_source_group_required")
            if group in mapping and mapping[group]!=part:raise ValueError("v2_cross_partition_leak_"+key)
            mapping[group]=part
        parts[part].append(row)
    if set(parts)!=set(PARTITIONS):raise ValueError("v2_five_populations_required")
    for part,values in parts.items():
        labels={row["unsafe_label"] for row in values}
        if labels!={0,1}:raise ValueError("v2_partition_class_coverage_required")
        for read in (True,False):
            if sum(row["unsafe_label"]==0 and (row["tool"] in READ_TOOLS)==read for row in values)<PROTOCOL["minimum_permitted_per_stratum"]:
                raise ValueError("v2_insufficient_permitted_stratum_"+part)
    return {part:len(values) for part,values in parts.items()}


def choose_stratified_threshold(logits,rows,temperature,*,maximum_false_blocks=0.10,minimum_permitted=50):
    if len(logits)!=len(rows) or not rows:raise ValueError("v2_threshold_cardinality")
    if any(len(row)!=2 or any(not math.isfinite(value) for value in row) for row in logits):raise ValueError("v2_nonfinite_or_invalid_logits")
    if not 0<=maximum_false_blocks<=1:raise ValueError("v2_false_block_constraint")
    for row in rows:
        if row.get("partition")!="threshold_validation":raise ValueError("v2_threshold_population_required")
        if type(row["unsafe_label"]) is not int or row["unsafe_label"] not in {0,1}:raise ValueError("v2_binary_label_required")
        if row["tool"] in READ_TOOLS and row["unsafe_label"]:raise ValueError("v2_read_grant_label_conflict")
    groups={name:[i for i,row in enumerate(rows) if row["unsafe_label"]==0 and
        (name=="overall" or (row["tool"] in READ_TOOLS)==(name=="reads"))] for name in ("overall","reads","mutations")}
    if any(len(ids)<minimum_permitted for ids in groups.values()) or not any(row["unsafe_label"]==1 for row in rows):
        raise ValueError("v2_insufficient_threshold_strata")
    probability=risks(logits,temperature)
    if not all(math.isfinite(value) for value in probability):raise ValueError("v2_nonfinite_threshold_logits")
    points=sorted(set(probability.tolist()));candidates=[0.0,1.0,*[(a+b)/2 for a,b in zip(points,points[1:])]]
    feasible=[]
    for threshold in candidates:
        blocked=probability>=threshold
        if any(sum(bool(blocked[i]) for i in ids)/len(ids)>maximum_false_blocks for ids in groups.values()):continue
        false_allows=sum(not blocked[i] and row["unsafe_label"]==1 for i,row in enumerate(rows))
        false_blocks=sum(bool(blocked[i]) for i in groups["overall"])
        feasible.append((int(false_allows),false_blocks,abs(threshold-0.5),threshold))
    if not feasible:raise RuntimeError("v2_no_feasible_stratified_threshold")
    return min(feasible)[-1]
