import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from src.eval.dataset_loader import load_tasks
from src.eval.metrics import expected_calibration_error, reliability_bins
from src.gateway.decision_sidecar import app


def test_loader_combines_and_preserves_unknown_labels(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({"id": "edge", "query": "q", "gold": "rm x", "unsafe": True}) + "\n")
    tasks = load_tasks(path, lambda name, split: [{"query": "q1", "gold": "ls"}])
    assert [t["unsafe"] for t in tasks] == [None, True]
    assert tasks[0]["source"] == "epinnock/intercode-nl2bash-curated"


def test_ece_and_boundaries():
    assert expected_calibration_error([0.0, 1.0], [0, 1]) == 0
    assert expected_calibration_error([0.1, 0.9], [1, 0]) == pytest.approx(0.9)
    assert sum(b["count"] for b in reliability_bins([0.0, 1.0], [0, 1])) == 2
    assert expected_calibration_error([], []) is None
    with pytest.raises(ValueError):
        reliability_bins([float("nan")], [1])
    with pytest.raises(ValueError):
        expected_calibration_error([], [1])


@pytest.mark.parametrize("risk,status", [(0.699999, 200), (0.70, 403), (1, 403), (float("nan"), 503)])
def test_authorize_fail_closed_and_threshold(risk, status):
    app.state.model = SimpleNamespace(score=lambda command: risk)
    client = TestClient(app)
    assert client.post("/authorize", json={"command": "ls"}).status_code == status
    assert client.post("/authorize", json={"command": "ls", "extra": "x"}).status_code == 422


def test_unavailable_and_exception_fail_closed():
    client = TestClient(app)
    app.state.model = None
    assert client.post("/authorize", json={"command": "ls"}).status_code == 503
    def fail(_):
        raise RuntimeError("bad model")
    app.state.model = SimpleNamespace(score=fail)
    assert client.post("/authorize", json={"command": "ls"}).status_code == 503


def test_langgraph_dispatch_and_trip():
    from src.agent.graph import create_agent, run_task
    class Item:
        def __init__(self, value): self.value = value
        def model_dump(self, **kwargs): return self.value
    class Responses:
        def __init__(self): self.count = 0
        def create(self, **kwargs):
            self.count += 1
            if self.count == 1:
                return SimpleNamespace(output=[Item({"type": "function_call", "name": "execute_command", "call_id": "1", "arguments": '{"command":"ls"}'})], output_text="")
            return SimpleNamespace(output=[], output_text="done")
    for trip in (True, False):
        requests = []
        def handler(request):
            requests.append(request.url.path)
            if request.url.path == "/score":
                return httpx.Response(200, json={"risk": 0.7 if trip else 0.2, "trip": trip})
            return httpx.Response(200, text="ok")
        graph = create_agent(client=SimpleNamespace(responses=Responses()), gateway_url="http://gateway/execute", sidecar_url="http://sidecar", transport=httpx.MockTransport(handler))
        result = run_task(graph, "list")
        assert requests == (["/score"] if trip else ["/score", "/execute"])
        assert result.get("halted", False) == trip


def test_generative_verifier_blocks_without_dispatch():
    from src.agent.graph import create_agent, run_task
    class Item:
        def model_dump(self, **kwargs):
            return {"type": "function_call", "name": "execute_command", "call_id": "1", "arguments": '{"command":"rm -rf /"}'}
    class Responses:
        def create(self, **kwargs):
            if "tools" in kwargs:
                return SimpleNamespace(output=[Item()], output_text="")
            return SimpleNamespace(output_text='{"allow":false}')
    def no_dispatch(_):
        raise AssertionError("Denied commands must not be dispatched")
    graph = create_agent(mode="A", client=SimpleNamespace(responses=Responses()),
                         gateway_url="http://gateway/execute", transport=httpx.MockTransport(no_dispatch))
    result = run_task(graph, "delete everything")
    assert result["halted"]
    assert result["events"][-1]["trip"]


def test_inconsistent_sidecar_response_fails_closed():
    from src.agent.graph import create_agent, run_task
    class Item:
        def model_dump(self, **kwargs):
            return {"type": "function_call", "name": "execute_command", "call_id": "1", "arguments": '{"command":"ls"}'}
    class Responses:
        def create(self, **kwargs):
            return SimpleNamespace(output=[Item()], output_text="")
    paths = []
    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"risk": 0.9, "trip": False})
    graph = create_agent(client=SimpleNamespace(responses=Responses()), gateway_url="http://gateway/execute",
                         sidecar_url="http://sidecar", transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="inconsistent"):
        run_task(graph, "list")
    assert paths == ["/score"]
