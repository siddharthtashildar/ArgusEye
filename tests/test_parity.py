"""Tests verifying mathematical parity between C++ firmware logic and Python research tools."""
import numpy as np
import pytest
from research.parity_test import EmbeddedDSPModel


def test_embedded_dsp_parity_quiescent():
    model = EmbeddedDSPModel(detector_mode=1, trigger_threshold=120)

    # Feed 100 constant samples (quiet room)
    for i in range(100):
        out = model.process_sample(raw_adc=12345, timestamp_us=i * 5000, delta_us=5000)

    assert out["sample_index"] == 100
    assert abs(out["baseline_adc"] - 12345) <= 1
    assert abs(out["ac_signal"]) <= 1
    assert out["filtered_signal"] == 0
    assert out["adaptive_motion"] is False
    assert out["legacy_motion"] is False
    assert out["selected_motion"] is False


def test_embedded_dsp_parity_burst_detection():
    model = EmbeddedDSPModel(detector_mode=1, trigger_threshold=120)

    # First initialize baseline with 50 samples
    for i in range(50):
        model.process_sample(raw_adc=12000, timestamp_us=i * 5000, delta_us=5000)

    # Inject a sinusoidal motion burst (amplitude 300, 30 Hz)
    detected = False
    for i in range(50, 100):
        val = int(12000 + 300.0 * np.sin(2.0 * np.pi * 30.0 * (i - 50) * 0.005))
        out = model.process_sample(raw_adc=val, timestamp_us=i * 5000, delta_us=5000)
        if out["selected_motion"]:
            detected = True

    assert detected is True
    assert model.event_count >= 1
    assert model.peak_signal > 200
