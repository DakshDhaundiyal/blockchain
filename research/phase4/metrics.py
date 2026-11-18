"""
TrustHarvest — Phase 4 Research Experiment Framework
Module: metrics.py

Computes statistical and classification evaluation metrics from experiment results:
- Classification accuracy
- Precision, Recall, F1-score (with safe zero-denominator handling)
- Latency statistics (mean, median, 95th-percentile, min, max)
- Explicit separation of 'cannot_verify' / RPC failure states from tampering detections
"""

import math
from typing import Any, Dict, List, Optional, Tuple


def _safe_divide(numerator: float, denominator: float, fallback: float = 0.0) -> float:
    """Safe division guarding against ZeroDivisionError and NaN."""
    if denominator == 0 or math.isnan(denominator) or math.isnan(numerator):
        return fallback
    return numerator / denominator


def calculate_latency_percentiles(latencies: List[float]) -> Dict[str, float]:
    """
    Computes summary latency metrics in milliseconds:
    Average (mean), Median (P50), 95th percentile (P95), Min, and Max.
    """
    if not latencies:
        return {
            "count": 0,
            "mean_ms": 0.0,
            "median_ms": 0.0,
            "p95_ms": 0.0,
            "min_ms": 0.0,
            "max_ms": 0.0,
        }

    sorted_l = sorted(latencies)
    n = len(sorted_l)
    mean_val = sum(sorted_l) / n

    # Median (P50)
    if n % 2 == 1:
        median_val = sorted_l[n // 2]
    else:
        median_val = (sorted_l[n // 2 - 1] + sorted_l[n // 2]) / 2.0

    # 95th percentile (nearest rank method)
    p95_idx = max(0, min(n - 1, math.ceil(0.95 * n) - 1))
    p95_val = sorted_l[p95_idx]

    return {
        "count": n,
        "mean_ms": round(mean_val, 3),
        "median_ms": round(median_val, 3),
        "p95_ms": round(p95_val, 3),
        "min_ms": round(sorted_l[0], 3),
        "max_ms": round(sorted_l[-1], 3),
    }


def compute_experiment_metrics(
    records: List[Dict[str, Any]],
    positive_label: str = "tampered",
    negative_label: str = "verified",
    inconclusive_label: str = "cannot_verify",
) -> Dict[str, Any]:
    """
    Evaluates experiment trial records.
    Important: Inconclusive states ('cannot_verify' or RPC offline) are strictly
    tracked in their own category and NEVER treated as ordinary tampering detections.
    """
    total = len(records)
    if total == 0:
        return {
            "total_samples": 0,
            "accuracy": 0.0,
            "precision": 0.0,
            "recall": 0.0,
            "f1_score": 0.0,
            "latency": calculate_latency_percentiles([]),
            "counts": {"correct": 0, "incorrect": 0, "tp": 0, "fp": 0, "tn": 0, "fn": 0, "inconclusive": 0},
        }

    correct_count = 0
    tp = 0  # Expected positive, actual positive
    fp = 0  # Expected negative, actual positive
    tn = 0  # Expected negative, actual negative
    fn = 0  # Expected positive, actual negative
    inconclusive_count = 0
    latencies: List[float] = []

    for r in records:
        exp = str(r.get("expected_outcome", "")).strip().lower()
        act = str(r.get("actual_outcome", "")).strip().lower()
        lat = float(r.get("latency_ms", 0.0))
        latencies.append(lat)

        if exp == act:
            correct_count += 1

        # Track inconclusive states separately (e.g., node offline, missing record)
        if act in (inconclusive_label, "rpc_offline", "cannot_check_right_now", "conflict"):
            inconclusive_count += 1
            if exp == positive_label:
                # Expected tamper, but system was inconclusive
                fn += 1
            elif exp == negative_label:
                # Expected verified, but system was inconclusive
                fp += 1
            continue

        if exp == positive_label and act == positive_label:
            tp += 1
        elif exp == negative_label and act == positive_label:
            fp += 1
        elif exp == negative_label and act == negative_label:
            tn += 1
        elif exp == positive_label and act == negative_label:
            fn += 1

    accuracy = _safe_divide(correct_count, total)
    precision = _safe_divide(tp, tp + fp)
    recall = _safe_divide(tp, tp + fn)
    f1 = _safe_divide(2 * precision * recall, precision + recall)

    # In baseline verification where all records are untampered (negative_label),
    # negative-class specificity (True Negative Rate) is the critical measure:
    specificity = _safe_divide(tn, tn + fp)

    latency_stats = calculate_latency_percentiles(latencies)

    # Per-stage accuracy breakdown
    stages = set(r.get("stage", "UNKNOWN") for r in records)
    stage_breakdown = {}
    for st in sorted(stages):
        st_records = [r for r in records if r.get("stage") == st]
        st_correct = sum(1 for r in st_records if r.get("expected_outcome") == r.get("actual_outcome"))
        st_latencies = [float(r.get("latency_ms", 0.0)) for r in st_records]
        stage_breakdown[st] = {
            "samples": len(st_records),
            "correct": st_correct,
            "accuracy": round(_safe_divide(st_correct, len(st_records)), 4),
            "latency_mean_ms": round(sum(st_latencies) / len(st_latencies), 3) if st_latencies else 0.0,
        }

    return {
        "total_samples": total,
        "correct_predictions": correct_count,
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1, 4),
        "specificity": round(specificity, 4),
        "inconclusive_count": inconclusive_count,
        "confusion_matrix": {
            "true_positives": tp,
            "false_positives": fp,
            "true_negatives": tn,
            "false_negatives": fn,
            "inconclusive": inconclusive_count,
        },
        "latency": latency_stats,
        "stage_breakdown": stage_breakdown,
    }


def format_metrics_summary(metrics: Dict[str, Any]) -> str:
    """Formats calculated metrics into a clean human-readable report."""
    lat = metrics["latency"]
    cm = metrics["confusion_matrix"]
    lines = [
        "=" * 68,
        "TRUSTHARVEST EXPERIMENT EVALUATION METRICS REPORT",
        "=" * 68,
        f"Total Samples Evaluated : {metrics['total_samples']}",
        f"Correct Predictions     : {metrics['correct_predictions']} / {metrics['total_samples']}",
        f"Classification Accuracy : {metrics['accuracy'] * 100:.2f}%",
        f"Precision (Tamper)      : {metrics['precision'] * 100:.2f}%",
        f"Recall (Tamper)         : {metrics['recall'] * 100:.2f}%",
        f"F1-Score                : {metrics['f1_score']:.4f}",
        f"Specificity (Verified)  : {metrics['specificity'] * 100:.2f}%",
        f"Inconclusive / Offline  : {metrics['inconclusive_count']}",
        "-" * 68,
        "LATENCY BENCHMARKS (ms):",
        f"  Mean Latency          : {lat['mean_ms']:.2f} ms",
        f"  Median Latency (P50)  : {lat['median_ms']:.2f} ms",
        f"  95th Percentile (P95) : {lat['p95_ms']:.2f} ms",
        f"  Min / Max Latency     : {lat['min_ms']:.2f} ms / {lat['max_ms']:.2f} ms",
        "-" * 68,
        "STAGE-LEVEL BREAKDOWN:",
    ]
    for st, data in metrics.get("stage_breakdown", {}).items():
        lines.append(
            f"  {st:<14} | Samples: {data['samples']:<3} | Acc: {data['accuracy']*100:.1f}% | Avg Latency: {data['latency_mean_ms']:.2f} ms"
        )
    lines.append("=" * 68)
    return "\n".join(lines)

