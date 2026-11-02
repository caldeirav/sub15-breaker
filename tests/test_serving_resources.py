from types import SimpleNamespace as S

import pytest

from src.benchmark.serving import ServingResources,provider_status


def test_llm_and_control_arms_never_load_classifier_weights(monkeypatch):
    calls=[];tok=object()
    monkeypatch.setattr("src.benchmark.serving.tokenizer",lambda *a,**kw:calls.append((a,kw)) or tok)
    monkeypatch.setattr("src.benchmark.serving.classifier_guard",lambda *a,**kw:pytest.fail("weights loaded"))
    resources=ServingResources("artifact",{})
    assert resources.select("llm") is None and resources.select("control") is None
    assert resources.projection_tokenizer() is resources.projection_tokenizer() is tok
    assert len(calls)==1 and not resources.snapshot()["classifier_weights_loaded"]


def test_switch_to_llm_releases_local_classifier_and_preserves_explicit_device(monkeypatch):
    closed=[];loads=[];tok=object()
    def load(*args,**kw):
        loads.append(kw);return S(close=lambda:closed.append(True)),tok
    monkeypatch.setattr("src.benchmark.serving.classifier_guard",load)
    resources=ServingResources("artifact",{},classifier_device="cpu")
    guard=resources.select("classifier")
    assert resources.select("classifier") is guard and len(loads)==1
    assert resources.projection_tokenizer() is tok
    resources.select("llm");resources.select("control")
    assert closed==[True] and loads==[dict(device="cpu")]
    assert resources.snapshot()["shared_model_reloaded"] is False
    assert resources.snapshot()["global_settings_changed"] is False


def test_classifier_load_failure_has_no_cpu_or_model_fallback(monkeypatch):
    devices=[]
    def fail(*a,**kw):devices.append(kw["device"]);raise RuntimeError("unavailable")
    monkeypatch.setattr("src.benchmark.serving.classifier_guard",fail)
    resources=ServingResources("artifact",{})
    with pytest.raises(RuntimeError,match="unavailable"):resources.select("classifier")
    assert devices==["mps"] and resources.classifier is None


def test_tokenizer_loader_is_local_verified_and_does_not_load_weights(monkeypatch):
    import transformers
    from src.benchmark.encoder import tokenizer
    calls=[]
    monkeypatch.setattr("src.benchmark.encoder.manifest",lambda *a,**kw:calls.append("verify"))
    monkeypatch.setattr(transformers.AutoTokenizer,"from_pretrained",lambda *a,**kw:calls.append(kw) or "tokenizer")
    monkeypatch.setattr(transformers.AutoModelForSequenceClassification,"from_pretrained",lambda *a,**kw:pytest.fail("weights loaded"))
    assert tokenizer("local",policy_id="policy")=="tokenizer"
    assert calls==["verify",dict(local_files_only=True,trust_remote_code=False)]


def test_encoder_close_is_local_idempotent_and_closed_encoder_cannot_infer(monkeypatch):
    from src.benchmark.encoder import EncoderLogit
    empty=[];encoder=EncoderLogit.__new__(EncoderLogit)
    encoder.model=S(device=S(type="mps"));encoder.torch=S(mps=S(empty_cache=lambda:empty.append(True)))
    monkeypatch.setattr("src.benchmark.encoder.gc.collect",lambda:None)
    encoder.close();encoder.close()
    assert encoder.model is None and empty==[True]
    with pytest.raises(RuntimeError,match="closed"):encoder("text")


@pytest.mark.parametrize("rows,state",[
    ([dict(identifier="model",status="idle",queued=0)],"idle"),
    ([dict(identifier="model",status="busy",queued=1)],"busy"),
    ([],"unobserved"),
    ([dict(identifier="other",status="idle",queued=0)],"unobserved")])
def test_provider_observer_only_reads_loaded_model_status(monkeypatch,rows,state):
    import json
    calls=[]
    monkeypatch.setattr("src.benchmark.serving.subprocess.check_output",lambda args,**kw:calls.append((args,kw)) or json.dumps(rows))
    assert provider_status("model",timeout_seconds=2)["state"]==state
    assert calls==[(["lms","ps","--json"],dict(text=True,timeout=2))]


def test_unavailable_provider_observer_never_implies_idle(monkeypatch):
    def fail(*a,**kw):raise OSError("unavailable")
    monkeypatch.setattr("src.benchmark.serving.subprocess.check_output",fail)
    assert provider_status("model")["state"]=="unobserved"


def test_encoder_stage_instrumentation_keeps_one_forward_and_unchanged_logits():
    from contextlib import nullcontext
    from src.benchmark.encoder import EncoderLogit
    calls=[]
    class Logits:
        def __getitem__(self,index):return self
        def float(self):return self
        def cpu(self):return self
        def tolist(self):return [1.0,3.0]
    class Model:
        device="cpu";config=S(max_position_embeddings=512)
        def __call__(self,**kw):calls.append(kw);return S(logits=Logits())
    class Tensor:
        shape=(1,2)
        def to(self,device):assert device=="cpu";return self
    class Tokenizer:
        model_max_length=512
        def __call__(self,text,**kw):assert kw==dict(return_tensors="pt",truncation=False);return dict(input_ids=Tensor())
    encoder=EncoderLogit.__new__(EncoderLogit);encoder.model=Model();encoder.tokenizer=Tokenizer();encoder.torch=S(inference_mode=nullcontext)
    assert encoder("text")==2.0 and len(calls)==1
    stages=encoder.last_timings_ns
    assert set(stages)=={"tokenization_ns","device_enqueue_ns","forward_and_host_result_ns","encoder_total_ns"}
    assert all(value>=0 for value in stages.values())
    assert sum(stages[k] for k in stages if k!="encoder_total_ns")==stages["encoder_total_ns"]
