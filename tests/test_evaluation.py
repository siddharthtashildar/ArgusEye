"""Tests for Experimental Evaluation Framework, Event Matching, and Metrics."""
import numpy as np
import pytest
from research.evaluation import match_events, evaluate_detections
from research.dsp_pipeline import MotionEvent


def test_event_matching_exact():
    gt = [
        MotionEvent(start_time=1.0, end_time=2.5, duration=1.5, peak_amplitude=200, start_idx=200, end_idx=500),
        MotionEvent(start_time=5.0, end_time=6.0, duration=1.0, peak_amplitude=150, start_idx=1000, end_idx=1200),
    ]
    pred = [
        # Match 1: slight latency (+0.1s)
        MotionEvent(start_time=1.1, end_time=2.4, duration=1.3, peak_amplitude=190, start_idx=220, end_idx=480),
        # Match 2: exact
        MotionEvent(start_time=5.05, end_time=6.0, duration=0.95, peak_amplitude=140, start_idx=1010, end_idx=1200),
    ]

    tp, fp, fn, lats = match_events(gt, pred, tolerance_s=0.4)
    assert tp == 2
    assert fp == 0
    assert fn == 0
    assert len(lats) == 2
    assert lats[0] == pytest.approx(100.0, abs=5.0)  # 0.1s = 100ms
    assert lats[1] == pytest.approx(50.0, abs=5.0)   # 0.05s = 50ms


def test_event_matching_false_alarm_and_miss():
    gt = [
        MotionEvent(start_time=2.0, end_time=3.0, duration=1.0, peak_amplitude=100, start_idx=400, end_idx=600),
    ]
    pred = [
        # Spurious detection outside GT window
        MotionEvent(start_time=8.0, end_time=9.0, duration=1.0, peak_amplitude=120, start_idx=1600, end_idx=1800),
    ]

    tp, fp, fn, lats = match_events(gt, pred, tolerance_s=0.4)
    assert tp == 0
    assert fp == 1
    assert fn == 1
    assert len(lats) == 0


def test_evaluate_detections_metrics():
    t = np.arange(1000) * 0.005  # 5 seconds
    gt = np.zeros(1000, dtype=bool)
    pred = np.zeros(1000, dtype=bool)

    # Event 1: t = 1.0 to 2.0 (indices 200 to 400)
    gt[200:400] = True
    # Predicted with 50ms latency (10 samples)
    pred[210:400] = True

    res = evaluate_detections(t, gt, pred, tolerance_s=0.4)
    assert res.true_positives == 1
    assert res.false_positives == 0
    assert res.false_negatives == 0
    assert res.precision == 1.0
    assert res.recall == 1.0
    assert res.f1_score == 1.0
    assert res.median_latency_ms == pytest.approx(50.0, abs=2.0)
    assert res.meets_targets["precision_gte_90"] is True
    assert res.meets_targets["recall_gte_90"] is True
    assert res.meets_targets["latency_lte_300ms"] is True
