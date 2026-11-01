"""Harmless transport fixtures do not constitute financial tools or inference."""
from http.client import HTTPConnection
import json
import threading

import pytest

from src.infra.protocol_fixture import FixtureServer, completion, mcp
from src.infra.protocol_client import LEGACY,MODERN,mcp_context
from src.infra.protocol_resources import FIXTURE_AUDIENCE, MODEL_AUDIENCE, MODEL_SUBJECT, manifests


def test_recording_completions_fixture_has_real_call_ids_decimal_strings_and_usage():
    result=completion(dict(model="fixture",messages=[dict(role="user",content="Synthetic")],tools=[{}]))
    call=result["choices"][0]["message"]["tool_calls"][0]
    assert call["id"]=="fixture-call-1"
    assert json.loads(call["function"]["arguments"])==dict(amount="123.40",note=None)
    assert result["choices"][0]["finish_reason"]=="tool_calls"
    assert result["usage"]["total_tokens"]==44
    result=completion(dict(messages=[dict(role="tool",tool_call_id="fixture-call-1",content="fixture result")]))
    assert result["choices"][0]["finish_reason"]=="stop"


def test_mcp_fixture_discovery_echo_and_unknown_tool_are_nonexecuting():
    init=mcp(dict(id=1,method="initialize",params=dict(protocolVersion=LEGACY)))
    assert init["result"]["protocolVersion"]==LEGACY
    assert [t["name"] for t in mcp(dict(id=2,method="tools/list"))["result"]["tools"]]==["echo_fixture"]
    assert mcp(dict(id=3,method="tools/call",params=dict(name="echo_fixture",arguments=dict(text="123.40"))))["result"]["content"][0]["text"]=="123.40"
    result=mcp(dict(id=4,method="tools/call",params=dict(name="execute_command",arguments=dict(command="never run"))))
    assert result["result"]["isError"] is True


def test_modern_mcp_is_sessionless_with_namespaced_metadata_and_routing_headers():
    original=dict(jsonrpc="2.0",id=1,method="tools/call",params=dict(name="echo_fixture",arguments=dict(text="value")))
    body,headers=mcp_context(original,MODERN)
    assert "_meta" not in original["params"]
    assert body["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"]==MODERN
    assert headers=={"mcp-protocol-version":MODERN,"mcp-method":"tools/call","mcp-name":"echo_fixture"}
    assert mcp_context(body,MODERN)[0]==body
    result=mcp(body)
    assert result["result"]["resultType"]=="complete" and result["result"]["content"][0]["text"]=="value"
    discovery=mcp(dict(id=2,method="server/discover",params={}))
    assert MODERN in discovery["result"]["supportedVersions"]
    assert "error" in mcp(dict(id=3,method="initialize",params=dict(protocolVersion=MODERN)))


def test_fixture_never_accepts_native_responses_or_records_credentials():
    server=FixtureServer(("127.0.0.1",0))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    connection=HTTPConnection(*server.server_address,timeout=3)
    try:
        connection.request("POST","/v1/responses",body='{"input":"fixture"}',headers={"authorization":"Bearer DO-NOT-RECORD","content-type":"application/json"})
        result=connection.getresponse()
        assert result.status==405;result.read()
        assert "DO-NOT-RECORD" not in json.dumps(server.records)
        connection.request("POST","/v1/chat/completions",body='{"messages":[],"messages":[]}',headers={"content-type":"application/json"})
        result=connection.getresponse()
        assert result.status==400;result.read()
        assert len(server.records)==1
    finally:
        connection.close();server.shutdown();server.server_close();thread.join(timeout=3)


def test_streaming_fixture_is_explicitly_unsupported():
    with pytest.raises(ValueError,match="streaming"):
        completion(dict(messages=[{}],stream=True))


def resources():
    return manifests(host_ip="192.168.127.254",model="local-qwen",issuer="https://issuer.invalid",
                     jwks={"keys":[{"kty":"RSA","kid":"fixture"}]},experiment_id="4")["items"]


def test_protocol_profile_uses_existing_managed_gateway_and_separate_listener():
    items=resources()
    gateway=next(i for i in items if i["kind"]=="Gateway")
    assert gateway["metadata"]["name"]=="breaker-gateway"
    assert gateway["spec"]["gatewayClassName"]=="agentgateway"
    assert gateway["spec"]["listeners"][0]["port"]==8081
    assert not any(i["kind"]=="Deployment" and "gateway" in i["metadata"]["name"] for i in items)
    routes={i["metadata"]["name"]:i["spec"] for i in items if i["kind"]=="HTTPRoute"}
    assert routes["banking-model-responses"]["parentRefs"][0]["sectionName"]=="http"
    assert routes["protocol-responses"]["parentRefs"][0]["sectionName"]=="infra-protocol"
    assert len(routes["banking-model-responses"]["rules"][0]["backendRefs"])==1


def test_only_completions_backend_no_layered_retries_and_exact_driver_identity():
    items=resources()
    backends={i["metadata"]["name"]:i["spec"] for i in items if i["kind"]=="AgentgatewayBackend"}
    model=backends["local-banking-model"]["ai"]["provider"]
    assert model["custom"]["formats"]==[dict(type="Completions",path="/v1/chat/completions")]
    assert model["host"]=="192.168.127.254" and model["port"]==1234
    for name in ["recording-completions","local-banking-model"]:
        assert backends[name]["policies"]["ai"]["routes"]=={"/v1/responses":"Responses"}
    identities={i["metadata"]["name"]:i["spec"]["traffic"] for i in items if i["kind"]=="AgentgatewayPolicy" and i["metadata"]["name"].endswith("-identity")}
    for name,policy in identities.items():
        assert policy["retry"]==dict(attempts=0)
        assert policy["jwtAuthentication"]["mode"]=="Strict"
        expected=MODEL_AUDIENCE if name=="banking-model-responses-identity" else FIXTURE_AUDIENCE
        assert policy["jwtAuthentication"]["providers"][0]["audiences"]==[expected]
    assert MODEL_SUBJECT in identities["banking-model-responses-identity"]["authorization"]["policy"]["matchExpressions"][0]


def test_trace_export_is_http_with_experiment_header_and_no_prompt_export():
    items=resources()
    trace=next(i["spec"]["frontend"]["tracing"] for i in items if i["metadata"]["name"]=="target-gateway-tracing")
    assert trace["protocol"]=="HTTP" and trace["path"]=="/v1/traces"
    assert "attributes" not in trace  # Do not add raw body/prompt/credential fields.
    backend=next(i["spec"] for i in items if i["metadata"]["name"]=="banking-mlflow-traces")
    assert backend["policies"]["auth"]["credentials"][0]["location"]["header"]["name"]=="x-mlflow-experiment-id"


def test_protocol_workloads_are_restricted_without_ambient_authority():
    for item in resources():
        if item["kind"]=="Pod":spec=item["spec"]
        elif item["kind"]=="Deployment":
            template=item["spec"]["template"]
            assert set(template)=={"metadata","spec"}
            assert "namespace" not in template["metadata"]
            spec=template["spec"]
        else:continue
        assert spec["automountServiceAccountToken"] is False
        assert spec["securityContext"]["runAsNonRoot"] is True
        assert spec["containers"][0]["securityContext"]["capabilities"]["drop"]==["ALL"]


@pytest.mark.parametrize("ip",["127.0.0.1","0.0.0.0","8.8.8.8","::1","example.com"])
def test_profile_cannot_accidentally_route_to_a_public_provider_or_pod_loopback(ip):
    with pytest.raises(ValueError):
        manifests(host_ip=ip,model="test",issuer="https://issuer.invalid",jwks={"keys":[{}]},experiment_id="4")
