"""ARGUS-EYE Experimental Evaluation Framework.
Computes event-level and sample-level performance metrics: Precision, Recall,
F1-score, False Alarm Rate (FAR/min), Detection Latency, and Confusion Matrix.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional
import numpy as np

from .dsp_pipeline import MotionEvent, extract_events, merge_events


@dataclass
class EvaluationResult:
    detector_name: str
    total_ground_truth_events: int
    total_predicted_events: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1_score: float
    false_alarms_per_minute: float
    stationary_duration_minutes: float
    median_latency_ms: float
    mean_latency_ms: float
    p90_latency_ms: float
    latencies_ms: List[float] = field(default_factory=list)
    sample_accuracy: float = 0.0
    sample_confusion_matrix: Dict[str, int] = field(default_factory=dict)
    meets_targets: Dict[str, bool] = field(default_factory=dict)
    condition_breakdown: Dict[str, Dict[str, float]] = field(default_factory=dict)


def match_events(
    ground_truth_events: List[MotionEvent],
    predicted_events: List[MotionEvent],
    tolerance_s: float = 0.4,
) -> Tuple[int, int, int, List[float]]:
    """Match predicted motion events against ground truth reference intervals.
    
    A predicted event matches a ground truth event if:
    1. It temporally overlaps with the GT event interval [start - tol, end + tol], OR
    2. Its onset is within tolerance_s of the GT onset.
    
    Returns:
        true_positives: number of ground truth events successfully detected
        false_positives: number of spurious detections outside any GT event
        false_negatives: number of missed ground truth events
        latencies_ms: detection onset latency in ms for each true positive
    """
    if not ground_truth_events:
        return 0, len(predicted_events), 0, []

    matched_gt = set()
    matched_pred = set()
    latencies_ms: List[float] = []

    for p_idx, p_ev in enumerate(predicted_events):
        best_gt_idx = None
        min_onset_diff = float("inf")

        for g_idx, g_ev in enumerate(ground_truth_events):
            # Check overlap or proximity
            window_start = g_ev.start_time - tolerance_s
            window_end = g_ev.end_time + tolerance_s

            if (p_ev.start_time <= window_end) and (p_ev.end_time >= window_start):
                diff = abs(p_ev.start_time - g_ev.start_time)
                if diff < min_onset_diff:
                    min_onset_diff = diff
                    best_gt_idx = g_idx

        if best_gt_idx is not None:
            matched_pred.add(p_idx)
            g_ev = ground_truth_events[best_gt_idx]
            if best_gt_idx not in matched_gt:
                matched_gt.add(best_gt_idx)
                # Latency: time from true event onset to predicted detection
                latency_s = max(0.0, p_ev.start_time - g_ev.start_time)
                latencies_ms.append(latency_s * 1000.0)

    tp = len(matched_gt)
    fp = len(predicted_events) - len(matched_pred)
    fn = len(ground_truth_events) - tp

    return tp, fp, fn, latencies_ms


def evaluate_detections(
    timestamps_s: np.ndarray,
    ground_truth_motion: np.ndarray,
    predicted_motion: np.ndarray,
    detector_name: str = "Detector",
    tolerance_s: float = 0.4,
    condition_labels: Optional[List[str]] = None,
) -> EvaluationResult:
    """Evaluate detector performance against labeled reference arrays."""
    # 1. Extract discrete event intervals
    gt_events = merge_events(extract_events(ground_truth_motion, timestamps_s, np.ones_like(timestamps_s)))
    pred_events = merge_events(extract_events(predicted_motion, timestamps_s, np.ones_like(timestamps_s)))

    tp, fp, fn, latencies_ms = match_events(gt_events, pred_events, tolerance_s=tolerance_s)

    precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
    f1 = float(2.0 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    # 2. Stationary / Quiet period calculation for False Alarms per minute
    stationary_mask = ~ground_truth_motion.astype(bool)
    dt_arr = np.diff(timestamps_s) if len(timestamps_s) > 1 else np.array([0.005])
    mean_dt = float(np.mean(dt_arr)) if len(dt_arr) else 0.005
    stationary_duration_s = float(np.sum(stationary_mask) * mean_dt)
    stationary_duration_min = max(0.001, stationary_duration_s / 60.0)

    # Count false alarms specifically during stationary periods
    false_alarms_per_min = float(fp / stationary_duration_min)

    # 3. Latency statistics
    if latencies_ms:
        med_lat = float(np.median(latencies_ms))
        mean_lat = float(np.mean(latencies_ms))
        p90_lat = float(np.percentile(latencies_ms, 90))
    else:
        med_lat = mean_lat = p90_lat = 0.0

    # 4. Frame-level sample confusion matrix
    gt_bool = ground_truth_motion.astype(bool)
    pred_bool = predicted_motion.astype(bool)

    sample_tp = int(np.sum(gt_bool & pred_bool))
    sample_fp = int(np.sum((~gt_bool) & pred_bool))
    sample_tn = int(np.sum((~gt_bool) & (~pred_bool)))
    sample_fn = int(np.sum(gt_bool & (~pred_bool)))
    total_samples = max(1, len(gt_bool))
    sample_acc = float((sample_tp + sample_tn) / total_samples)

    sample_cm = {
        "TP": sample_tp,
        "FP": sample_fp,
        "TN": sample_tn,
        "FN": sample_fn,
    }

    # 5. Check engineering goals:
    # - Precision >= 90%
    # - Recall >= 90%
    # - False alarms <= 1.0 / min in stationary test
    # - Median latency <= 300 ms
    has_gt_events = len(gt_events) > 0
    meets_targets = {
        "precision_gte_90": (precision >= 0.90) if has_gt_events else (fp == 0),
        "recall_gte_90": (recall >= 0.90) if has_gt_events else True,
        "false_alarms_lte_1_per_min": false_alarms_per_min <= 1.0,
        "latency_lte_300ms": (med_lat <= 300.0) if has_gt_events else True,
    }

    return EvaluationResult(
        detector_name=detector_name,
        total_ground_truth_events=len(gt_events),
        total_predicted_events=len(pred_events),
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1_score=f1,
        false_alarms_per_minute=false_alarms_per_min,
        stationary_duration_minutes=stationary_duration_min,
        median_latency_ms=med_lat,
        mean_latency_ms=mean_lat,
        p90_latency_ms=p90_lat,
        latencies_ms=latencies_ms,
        sample_accuracy=sample_acc,
        sample_confusion_matrix=sample_cm,
        meets_targets=meets_targets,
    )
