"""Small Envoy ext_proc adapter for Substrate's additional egress hook.

The benchmark bridge registers a service-prepared immutable ticket. The Actor
claims THAT ticket in its URL; the store consumes the URL, not a body proposal.
This module alone does not prove native enforcement: use actual Actor controls.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
import re
import threading
from time import perf_counter_ns

import grpc
import mlflow
from src.benchmark import extproc_wire as pb

from src.benchmark.guards import Verdict,timed_review


class ControlGuard:
    def __init__(self,decision):
        if decision not in {"allow","block","error"}:raise ValueError("invalid_control_guard")
        self.decision=decision;self.guard_id="deterministic-native-"+decision

    def review(self,value):
        if self.decision=="error":raise RuntimeError("deliberate_control_error")
        return Verdict(value.digest(),self.decision,self.guard_id)


@dataclass
class Entry:
    value: object
    guard: object
    parent: object
    result: dict | None = None
    attempted: bool = False


class Registry:
    def __init__(self):
        self.entries={};self.lock=threading.Lock()

    def register(self,ticket,value,guard,*,parent=None):
        if not re.fullmatch(r"[0-9a-f]{32}",ticket):raise ValueError("invalid_prepared_ticket")
        with self.lock:
            if ticket in self.entries:raise ValueError("duplicate_guard_ticket")
            self.entries[ticket]=Entry(deepcopy(value),guard,parent)

    def admit(self,ticket):
        started=perf_counter_ns()
        with self.lock:
            entry=self.entries.get(ticket)
            if entry is None or entry.attempted:return dict(decision="error",error="unregistered_or_replayed_ticket")
            entry.attempted=True
        span=mlflow.start_span_no_context(name="substrate_native_admission",span_type="GUARDRAIL",parent_span=entry.parent)
        try:
            span.set_inputs(dict(ticket=ticket,review=entry.value.serialized(),guard_id=entry.guard.guard_id))
            # Context attachment makes LangChain verifier autolog spans children
            # of this actual platform admission, even on the gRPC worker thread.
            from mlflow.tracing.fluent import with_active_span
            with with_active_span(span):
                result=timed_review(entry.guard,entry.value)
            result.update(ticket=ticket,admission_service_ns=perf_counter_ns()-started,
                trace_id=span.trace_id,span_id=span.span_id)
            span.set_outputs(result)
            with self.lock:entry.result=result
            return result
        finally:span.end()

    def result(self,ticket):
        with self.lock:
            entry=self.entries.get(ticket)
            return deepcopy(entry.result) if entry else None


class Processor:
    def __init__(self,registry,store_host):self.registry,self.store_host=registry,store_host

    def Process(self,request_iterator,context):
        for request in request_iterator:
            if request.WhichOneof("request")!="request_headers":
                yield deny(503,"unsupported_processing_phase");return
            headers={}
            for header in request.request_headers.headers.headers:
                key=header.key.lower()
                if key in headers:
                    yield deny(400,"duplicate_request_header");return
                headers[key]=header.raw_value.decode() if header.raw_value else header.value
            host=headers.get(":authority","").split(":")[0]
            path=headers.get(":path","")
            if host==self.store_host and path.startswith("/claim"):
                match=re.fullmatch(r"/claim/([0-9a-f]{32})",path)
                if headers.get(":method")!="POST" or not match:
                    yield deny(403,"canonical_ticket_path_required");return
                result=self.registry.admit(match[1])
                if result["decision"]!="allow":
                    yield deny(403 if result["decision"]=="block" else 503,"benchmark_guard_"+result["decision"]);return
            yield pb.ProcessingResponse(request_headers=pb.HeadersResponse())


def deny(status,reason):
    return pb.ProcessingResponse(immediate_response=pb.ImmediateResponse(status={"code":status},
        body=reason.encode(),details=reason))


def server(registry,store_host,address):
    service=grpc.server(ThreadPoolExecutor(max_workers=4),options=[("grpc.max_receive_message_length",262144)])
    pb.add_processor(Processor(registry,store_host),service)
    if not service.add_insecure_port(address):raise RuntimeError("native_guard_bind_failed")
    service.start()
    return service
