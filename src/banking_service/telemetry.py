"""Replay durable events to MLflow; acknowledge only verified persisted evidence."""
import mlflow

SOURCE = mlflow.entities.AssessmentSource(source_type="CODE",source_id="banking-actor-service-v1")


def log_receipt_scores(record):
    """Expose receipt facts on the owning action span without replacing oracles."""
    from src.banking_contracts.models import ExecutionReceipt
    trace=mlflow.get_trace(record["trace_id"])
    if trace is None:raise RuntimeError("Missing receipt target trace")
    if record.get("child_run_id") and trace.info.trace_metadata.get("mlflow.sourceRun")!=record["child_run_id"]:
        raise RuntimeError("Receipt target run ownership differs")
    seen=set()
    for action in record["evidence"]["actions"]:
        if action["span_id"] in seen:raise RuntimeError("Duplicate receipt action span")
        seen.add(action["span_id"])
        spans=[s for s in trace.data.spans if s.span_id==action["span_id"] and s.span_type=="TOOL"]
        if len(spans)!=1 or spans[0].outputs!=action:raise RuntimeError("Receipt does not belong to the recorded action span")
        raw=action.get("execution_receipt")
        values={"tool/receipt_available":raw is not None}
        if raw is not None:
            receipt=ExecutionReceipt.model_validate(raw)
            if receipt.fixture_only:raise RuntimeError("Record-only receipt cannot prove Actor execution")
            if receipt.executed is not None:values["tool/executed"]=receipt.executed
            # MLflow numeric feedback is serialized through doubles. Preserve
            # the integer contract exactly, including values beyond 2**53.
            values["tool/state_version_before_exact"]=str(receipt.state_version_before)
            if receipt.state_version_after is not None:values["tool/state_version_after_exact"]=str(receipt.state_version_after)
        for name,value in values.items():
            existing=[a for a in trace.info.assessments if a.name==name and a.span_id==action["span_id"]]
            if existing:
                if (len(existing)!=1 or existing[0].error is not None or type(existing[0].value) is not type(value) or
                        existing[0].value!=value or existing[0].source is None or existing[0].source.source_type!="CODE" or
                        existing[0].source.source_id!="banking-actor-service-v1"):
                    raise RuntimeError("Receipt assessment owner/value is ambiguous")
            else:mlflow.log_feedback(trace_id=record["trace_id"],span_id=action["span_id"],name=name,value=value,source=SOURCE)


def export_outbox(client, experiment_id):
    exported=[]
    for _ in range(40):  # bounded by the service outbox capacity, never an infinite drain
        events=client.call("/events",{})["events"]
        if not events:return exported
        for event in events:
            matches=mlflow.search_traces(experiment_ids=[experiment_id],return_type="list",max_results=2,
                filter_string=f"metadata.`banking.event_id` = '{event['event_id']}'")
            if len(matches)>1:raise RuntimeError("Ambiguous durable event traces")
            if matches:
                trace_id=matches[0].info.trace_id
            else:
                with mlflow.start_span(name="durable_"+event["kind"],span_type="CHAIN") as span:
                    mlflow.update_current_trace(metadata={"banking.event_id":event["event_id"],"banking.trial_id":event["trial_id"]})
                    span.set_inputs(dict(event_id=event["event_id"],kind=event["kind"],origin="durable-service-outbox"))
                    span.set_outputs(event)
                    trace_id=span.trace_id
            trace=mlflow.get_trace(trace_id)
            if trace is None:raise RuntimeError("Missing exported durable event")
            roots=[s for s in trace.data.spans if s.parent_id is None]
            if len(roots)!=1 or roots[0].outputs!=event:
                raise RuntimeError("Durable-event trace contents differ")
            # A trace may have persisted before a feedback request failed. Repair
            # only absent assessments, never replace another issuer or value.
            for name,value in {"runtime/event_kind":event["kind"],"runtime/durable_event":True}.items():
                present=[a for a in trace.info.assessments if a.name==name and a.span_id is None]
                if not present:
                    mlflow.log_feedback(trace_id=trace_id,name=name,value=value,source=SOURCE)
                elif (len(present)!=1 or type(present[0].value) is not type(value) or present[0].value!=value or present[0].error is not None or
                        present[0].source is None or present[0].source.source_type!="CODE" or
                        present[0].source.source_id!="banking-actor-service-v1"):
                    raise RuntimeError("Ambiguous or wrong-owner durable-event assessment")
            trace=mlflow.get_trace(trace_id)
            if trace is None:raise RuntimeError("Missing durable-event readback")
            roots=[s for s in trace.data.spans if s.parent_id is None]
            if len(roots)!=1 or roots[0].outputs!=event:
                raise RuntimeError("Durable-event evidence/score ownership mismatch")
            for name,value in {"runtime/event_kind":event["kind"],"runtime/durable_event":True}.items():
                scores=[a for a in trace.info.assessments if a.name==name and a.span_id is None]
                if (len(scores)!=1 or type(scores[0].value) is not type(value) or scores[0].value!=value or scores[0].error is not None or scores[0].source is None or
                        scores[0].source.source_type!="CODE" or scores[0].source.source_id!="banking-actor-service-v1"):
                    raise RuntimeError("Durable-event evidence/score ownership mismatch")
            client.call("/acknowledge",dict(event_id=event["event_id"]))
            exported.append(dict(event_id=event["event_id"],trace_id=trace_id,kind=event["kind"],trial_id=event["trial_id"]))
    if not client.call("/events",{})["events"]:return exported
    raise RuntimeError("Outbox exceeds bounded export budget")
