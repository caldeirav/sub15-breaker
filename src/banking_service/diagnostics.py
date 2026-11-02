"""Bounded runtime transport metadata. Never include bodies, URLs or credentials."""
import re

from src.banking_contracts.codec import ContractError

BOUNDARIES={"runtime_client","driver_to_actor","driver_to_store","actor_to_store","actor_to_store_readiness","actor_to_store_commit"}
OPERATIONS={"actor-readiness","admission-readiness","claim","commit","create","snapshot","prepare","status","reconcile","fence","replace","events","trial-events","acknowledge","client-event","capacity","reserve-capacity","release-capacity","probe","execute","other"}
FAILURES={"success","invalid_json","http_error","too_large","transport_error","unsupported_encoding"}
MEDIA={"application/json","application/problem+json","text/plain","text/html","application/grpc","absent","other"}
ERRORS={"ConnectTimeout","ReadTimeout","WriteTimeout","PoolTimeout","ConnectError","ReadError","WriteError","CloseError","RemoteProtocolError","LocalProtocolError","ProxyError","UnsupportedProtocol","DecodingError","TransportError"}


def operation(path):
    name=path.strip("/").split("/",1)[0]
    return name if name in OPERATIONS else "other"


def sanitize_chain(value):
    if not isinstance(value,dict) or value.get("schema_version")!="runtime-transport-chain-v1" or not isinstance(value.get("hops"),list):return []
    result=[]
    for hop in value["hops"][:4]:
        if not isinstance(hop,dict):continue
        safe={}
        for key,allowed in (("boundary",BOUNDARIES),("operation",OPERATIONS),("failure",FAILURES),("content_type",MEDIA),("exception_type",ERRORS),("body_digest_scope",{"complete","bounded_prefix","partial"})):
            if isinstance(hop.get(key),str) and hop[key] in allowed:safe[key]=hop[key]
        for key in ("elapsed_ns","body_bytes"):
            if type(hop.get(key)) is int and 0<=hop[key]<=2**63-1:safe[key]=hop[key]
        if type(hop.get("status")) is int and 100<=hop["status"]<=599:safe["status"]=hop["status"]
        elif hop.get("status") is None:safe["status"]=None
        for key,size in (("operation_id",32),("body_sha256",64)):
            if isinstance(hop.get(key),str) and re.fullmatch(r"[0-9a-f]{"+str(size)+"}",hop[key]):safe[key]=hop[key]
        result.append(safe)
    return result


class RuntimeCallError(ContractError):
    def __init__(self,code,hop,upstream=None):
        super().__init__(code,"transport")
        self.transport=dict(schema_version="runtime-transport-chain-v1",hops=sanitize_chain(dict(schema_version="runtime-transport-chain-v1",hops=[hop]))+sanitize_chain(upstream)[:3])
