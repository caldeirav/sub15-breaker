"""Calibration metrics computed from independent labels."""
import math


def reliability_bins(scores, labels, bins=10):
    if bins < 1 or len(scores) != len(labels):
        raise ValueError("Invalid bins or mismatched lengths")
    buckets = [[] for _ in range(bins)]
    for score, label in zip(scores, labels):
        if not math.isfinite(score) or not 0 <= score <= 1 or label not in (0, 1):
            raise ValueError("Invalid probability or label")
        buckets[min(int(score * bins), bins - 1)].append((score, int(label)))
    return [{"bin": i, "count": len(items),
             "confidence": sum(p for p, _ in items) / len(items),
             "frequency": sum(y for _, y in items) / len(items)}
            for i, items in enumerate(buckets) if items]


def expected_calibration_error(scores, labels, bins=10):
    if len(scores) != len(labels) or bins < 1:
        raise ValueError("Invalid bins or mismatched lengths")
    if not scores:
        return None
    groups = reliability_bins(scores, labels, bins)
    return sum(x["count"] * abs(x["confidence"] - x["frequency"]) for x in groups) / len(scores)
