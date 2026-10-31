"""Fit temperature on held-out binary logits, never on the evaluation set."""
import json
import math
import sys

from scipy.optimize import minimize_scalar
from scipy.special import logsumexp


def fit_temperature(rows):
    if not rows:
        raise ValueError("Need held-out labeled logits")
    if any(len(r["logits"]) != 2 or r["label"] not in (0, 1) or
           not all(math.isfinite(x) for x in r["logits"]) for r in rows):
        raise ValueError("Expected finite two-class logits and binary labels")
    def loss(log_temperature):
        t = math.exp(log_temperature)
        return sum(logsumexp([x / t for x in r["logits"]]) - r["logits"][r["label"]] / t for r in rows) / len(rows)
    result = minimize_scalar(loss, bounds=(-5, 5), method="bounded")
    if not result.success:
        raise RuntimeError("Temperature fit failed")
    return math.exp(result.x)


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        print(fit_temperature([json.loads(line) for line in f if line.strip()]))
