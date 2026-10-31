"""Fail-closed, non-generative binary sequence classifier authorization service."""
import math
import os
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

THRESHOLD = 0.70


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str = Field(min_length=1, max_length=8192)


class RiskModel:
    def __init__(self, path, temperature):
        if not path or not math.isfinite(temperature) or temperature <= 0:
            raise ValueError("Set RISK_MODEL_PATH and a positive fitted RISK_TEMPERATURE")
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        self.torch = torch
        self.temperature = temperature
        self.tokenizer = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForSequenceClassification.from_pretrained(path).eval()
        if self.model.config.num_labels != 2:
            raise ValueError("Expected binary classifier (class 1 = unsafe)")

    def score(self, command):
        inputs = self.tokenizer(command, return_tensors="pt", truncation=False)
        max_tokens = min(self.tokenizer.model_max_length, self.model.config.max_position_embeddings)
        if inputs["input_ids"].shape[1] > max_tokens:
            raise ValueError("Input exceeds model context; refusing truncated authorization")
        with self.torch.inference_mode():
            logits = self.model(**inputs).logits[0]
            return float(self.torch.softmax(logits / self.temperature, dim=-1)[1])


@asynccontextmanager
async def lifespan(app):
    try:
        app.state.model = RiskModel(os.getenv("RISK_MODEL_PATH"), float(os.getenv("RISK_TEMPERATURE", "nan")))
    except Exception as exc:
        app.state.model = None
        app.state.startup_error = str(exc)
    yield


app = FastAPI(lifespan=lifespan)


def decide(command, model):
    if model is None:
        raise HTTPException(503, "Risk classifier unavailable")
    started = perf_counter()
    try:
        risk = model.score(command)
    except Exception as exc:
        raise HTTPException(503, "Risk classifier failed") from exc
    if not math.isfinite(risk) or not 0 <= risk <= 1:
        raise HTTPException(503, "Invalid model output")
    return {"risk": risk, "trip": risk >= THRESHOLD, "latency_ms": (perf_counter() - started) * 1000}


@app.get("/health")
def health(request: Request):
    if getattr(request.app.state, "model", None) is None:
        raise HTTPException(503, "Risk classifier unavailable")
    return {"ready": True}


@app.post("/score")
def score(body: Command, request: Request):
    return decide(body.command, getattr(request.app.state, "model", None))


@app.post("/authorize")
def authorize(body: Command, request: Request):
    result = decide(body.command, getattr(request.app.state, "model", None))
    if result["trip"]:
        raise HTTPException(403, detail=result)
    return result
