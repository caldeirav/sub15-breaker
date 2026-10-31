"""Explore recorded benchmark data, never assumed performance targets."""
import json
import os

import mlflow
import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

from src.eval.metrics import expected_calibration_error, reliability_bins

load_dotenv()
mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI") or "sqlite:///mlflow.db")
st.title("BreakerSubstrate benchmark")
experiment = mlflow.get_experiment_by_name("breaker-substrate")
if experiment is None:
    st.info("No benchmark runs found.")
    st.stop()
runs = mlflow.search_runs([experiment.experiment_id])
if runs.empty:
    st.info("No benchmark runs found.")
    st.stop()
run_id = st.selectbox("Run", runs["run_id"].tolist())
try:
    path = mlflow.artifacts.download_artifacts(run_id=run_id, artifact_path="traces.json")
    with open(path, encoding="utf-8") as f:
        traces = json.load(f)
except Exception as exc:
    st.error(f"Could not load traces: {exc}")
    st.stop()
events = []
for trace in traces:
    for event in trace.get("result", {}).get("events", []):
        events.append({**event, "mode": trace["mode"], "task": trace["task"]})
decisions = [e for e in events if e.get("step") == "verification"]
if not decisions:
    st.info("No verification decisions recorded.")
    st.stop()
frame = pd.DataFrame([{**e, "task": e["task"]["id"]} for e in decisions])
st.subheader("Observed verification latency (ms)")
st.plotly_chart(px.histogram(frame, x="latency_ms", color="mode", barmode="overlay"))
st.caption("Target comparison: generative ~1,500 ms, sidecar <15 ms; actual measurements shown above.")
st.subheader("Circuit breaker")
st.metric("Decision trip rate", f"{frame['trip'].mean():.1%}")
prevented = sum(e["trip"] and e["task"].get("unsafe") is True and e["command"] == e["task"]["gold"] for e in decisions)
st.metric("Labeled destructive reference commands blocked", prevented)
st.caption("A blocked request is not proof that the actor was terminated or that other effects were contained.")
labeled = [e for e in decisions if e["mode"] == "B" and e.get("risk") is not None and e["task"].get("unsafe") is not None and e["command"] == e["task"]["gold"]]
st.subheader("Reliability and ECE")
if labeled:
    scores = [e["risk"] for e in labeled]
    labels = [int(e["task"]["unsafe"]) for e in labeled]
    groups = reliability_bins(scores, labels)
    fig = px.line(pd.DataFrame(groups), x="confidence", y="frequency", markers=True, range_x=[0, 1], range_y=[0, 1])
    fig.add_scatter(x=[0, 1], y=[0, 1], mode="lines", name="Perfect calibration")
    st.plotly_chart(fig)
    st.metric("ECE", f"{expected_calibration_error(scores, labels):.3f}")
    st.caption(f"Based on {len(labeled)} labeled reference-command decisions.")
else:
    st.info("No independently labeled matching commands; ECE is unavailable.")
