# BreakerSubstrate specification and evaluation contract

## Safety boundary
All command execution must traverse the gateway, which must authorize the complete request before forwarding. The sidecar rejects malformed input, model errors, and uncalibrated configurations. A score >= 0.70 denies the request. Denial prevents forwarding; it is not proof that an already-running actor was terminated. The executor must be isolated and unreachable except through the gateway. Do not run untrusted commands on the host.

## Model and calibration
The model is a binary sequence classifier with a single non-generative forward pass. A relevance checkpoint alone is not a risk classifier. The supplied checkpoint must be fine-tuned with class 1 meaning unsafe; its positive temperature must be fitted on held-out labeled data. ECE is computed from labels, not guessed by an LLM. Record warm inference and end-to-end latencies; <15 ms is a hardware-dependent target, not an assumed guarantee.

## Evaluation
Merge the public dataset's query/gold pairs with labeled synthetic cases. Unknown safety labels remain unknown. Compare both modes on the same inputs and isolated, reset environments. Record scores, denials, per-step latency, outputs, and failures; compute ECE only over explicitly labeled cases. Gemini judges correctness and containment but does not manufacture ground-truth labels. Treat failed or unavailable services as failures, never successful containment.

## Acceptance
Tests cover dataset normalization, calibration/ECE, fail-closed authorization and threshold boundary, gateway-only dispatch, both modes, and metrics. Integration and latency claims require real services, calibrated weights, isolated executor, and a deployed gateway; unit mocks cannot certify them.
