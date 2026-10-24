"""Tests for ARGUS-EYE DSP Pipeline, Filtering, Envelopes, and Detectors."""
import numpy as np
import pytest
from research.dsp_pipeline import (
    moving_average,
    exponential_smoothing,
    butter_bandpass_filter,
    compute_envelope_hilbert,
    compute_envelope_causal,
    estimate_baseline,
    estimate_noise_floor,
    detect_motion_legacy,
    detect_motion_adaptive,
    extract_events,
    merge_events,
    MotionEvent,
    RadarDSPPipeline,
)


def test_moving_average():
    data = np.array([10.0, 10.0, 10.0, 10.0, 10.0])
    res = moving_average(data, window_size=3)
    assert len(res) == 5
    assert np.allclose(res, 10.0)


def test_exponential_smoothing():
    data = np.ones(50) * 100.0
    res = exponential_smoothing(data, alpha=0.1)
    assert len(res) == 50
    assert res[0] == 100.0
    assert np.allclose(res[-1], 100.0, atol=0.1)


def test_butter_bandpass_filter_nyquist_safety():
    fs = 200.0
    t = np.arange(200) / fs
    # Composite signal: DC offset + 30 Hz Doppler + 120 Hz HF noise
    sig = 500.0 + 100.0 * np.sin(2 * np.pi * 30 * t) + 50.0 * np.sin(2 * np.pi * 95 * t)

    # Filtering between 5 Hz and 80 Hz should reject DC offset
    filtered = butter_bandpass_filter(sig, lowcut=5.0, highcut=80.0, fs=fs, causal=False)
    assert len(filtered) == len(sig)
    assert abs(np.mean(filtered)) < 5.0  # DC removed

    # Test edge case: highcut exceeding Nyquist should be gracefully clamped without crash
    clamped = butter_bandpass_filter(sig, lowcut=5.0, highcut=150.0, fs=fs, causal=True)
    assert len(clamped) == len(sig)


def test_envelope_followers():
    fs = 200.0
    t = np.arange(200) / fs
    carrier = 100.0 * np.sin(2 * np.pi * 20 * t)

    env_causal = compute_envelope_causal(carrier, attack=0.35, decay=0.05)
    env_hilbert = compute_envelope_hilbert(carrier)

    assert len(env_causal) == 200
    assert len(env_hilbert) == 200
    assert np.max(env_causal) > 75.0
    assert np.max(env_hilbert) > 90.0


def test_legacy_detector():
    raw = np.array([1000, 1000, 1045, 1060, 1000])
    baseline = np.ones(5) * 1000
    # deadband=50, threshold=30:
    # sig: [0, 0, 45, 60, 0]
    # after deadband (abs < 50): [0, 0, 0, 60, 0]
    # threshold 30: only index 3 is > 30
    motion = detect_motion_legacy(raw, baseline, deadband=50, threshold=30)
    assert not motion[0]
    assert not motion[1]
    assert not motion[2]  # 45 is suppressed by deadband 50
    assert motion[3]      # 60 survives deadband and exceeds threshold 30
    assert not motion[4]


def test_adaptive_detector_hysteresis_and_confirmation():
    # 20 samples: quiet -> 4 strong samples -> quiet
    env = np.array([
        10.0, 10.0, 10.0,          # quiet
        150.0, 150.0, 150.0, 150.0,# strong burst
        20.0, 20.0, 20.0, 20.0,    # below release
    ])
    # confirm_samples=3: requires 3 samples above trigger before asserting motion
    motion, trig, rel = detect_motion_adaptive(
        env,
        noise_floor=15.0,
        min_thresh=60,
        confirm_samples=3,
        hold_samples=2,
    )
    # Samples 0, 1, 2 are quiet
    assert not motion[0] and not motion[1] and not motion[2]
    # Sample 3, 4 are above threshold but waiting confirmation
    assert not motion[3] and not motion[4]
    # Sample 5 is 3rd consecutive above threshold -> motion asserted!
    assert motion[5]
    assert motion[6]


def test_event_extraction_and_merging():
    motion = np.array([0, 0, 1, 1, 1, 0, 1, 1, 0, 0], dtype=bool)
    timestamps = np.arange(10) * 0.1
    magnitude = np.ones(10) * 50.0

    raw_events = extract_events(motion, timestamps, magnitude)
    assert len(raw_events) == 2

    # Merge events with gap <= 0.2s
    merged = merge_events(raw_events, max_gap_s=0.25)
    assert len(merged) == 1
    assert merged[0].start_time == pytest.approx(0.2)
    assert merged[0].end_time == pytest.approx(0.7)


def test_radar_dsp_pipeline_batch():
    pipeline = RadarDSPPipeline(fs=200.0)
    raw = np.full(400, 12000.0)
    # Inject a 50-sample burst
    raw[150:200] += 300.0 * np.sin(2 * np.pi * 30 * np.arange(50) / 200.0)

    res = pipeline.run(raw)
    assert "raw_adc" in res
    assert "signal_bpf_causal" in res
    assert "envelope_causal" in res
    assert "adaptive_motion" in res
    assert np.any(res["adaptive_motion"])
