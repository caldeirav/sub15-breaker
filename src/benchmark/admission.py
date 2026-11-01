"""Real guard adapters for the existing remote native gate; no extra agent loop."""
import mlflow

from src.banking_contracts.tools import READ_TOOLS
from src.benchmark.encoder import EncoderLogit
from src.benchmark.guards import Calibration,ClassifierGuard,LLMGuard
from src.benchmark.privacy import Mask
from src.benchmark.projection import POLICY_ID,credential_facts,project


class ReviewBuilder:
    def __init__(self,tokenizer,*,maximum=2048):self.tokenizer,self.maximum=tokenizer,maximum
    def __call__(self,snapshot,tool,arguments,actions):
        goal=snapshot["context"]["user_request"]
        mask=Mask();mask.learn(snapshot["state"]);mask.learn(arguments)
        observations=[dict(tool=item["tool"],arguments=item["arguments"],output=item["output"]) for item in actions
            if item.get("status")=="executed" and item["tool"] in READ_TOOLS]
        return project(mask(goal),tool,mask(arguments),state=mask(snapshot["state"]),observations=mask(observations),
            credential_context=credential_facts(goal,arguments) if tool=="update_password" else None,
            token_count=lambda value:len(self.tokenizer(value,truncation=False)["input_ids"]),maximum_tokens=self.maximum)


def classifier_guard(artifact,calibration,*,device="mps"):
    encoder=EncoderLogit(artifact,policy_id=POLICY_ID,device=device)
    if calibration!=encoder.manifest.get("calibration"):
        raise ValueError("classifier_frozen_calibration_mismatch")
    def forward(value):
        with mlflow.start_span(name="encoder_classifier_forward",span_type="CHAIN") as span:
            span.set_inputs(dict(model_id=encoder.model_id,review_input=value))
            result=encoder(value);span.set_outputs(dict(unsafe_logit_difference=result));return result
    fields={name:calibration[name] for name in ("model_id","policy_id","calibration_set_id","temperature","threshold","input_version")}
    return ClassifierGuard(forward,Calibration(**fields),model_id=encoder.model_id),encoder.tokenizer


def llm_guard(model,*,guard_id,reserve_model):
    return LLMGuard(model,guard_id=guard_id,reserve_model=reserve_model)
