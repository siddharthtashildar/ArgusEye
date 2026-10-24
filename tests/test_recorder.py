"""Tests for CSV telemetry recording, metadata serialization, and loading."""
from pathlib import Path
import numpy as np
import pytest
from research.recorder import SessionRecorder, load_recording
from research.protocol import TelemetryPacket


def test_session_recorder_and_loader(tmp_path):
    csv_file = tmp_path / "test_session.csv"
    recorder = SessionRecorder()

    recorder.start(
        output_csv_path=csv_file,
        experiment_name="unit_test_run",
        condition="walking",
        notes="Automated recorder test",
        target_distance_m=1.5,
        nominal_sample_rate_hz=200.0,
    )

    # Write 10 samples
    for i in range(10):
        pkt = TelemetryPacket(
            raw=12000 + i * 5,
            baseline=12000,
            signal=i * 5,
            firmware_motion=(i >= 7),
            seq=i + 1,
            t_us=i * 5000,
            filtered=i * 4,
            envelope=i * 5,
            noise_floor=12,
            threshold=80,
        )
        recorder.write_sample(pkt, ground_truth_motion=1 if i >= 6 else 0)

    saved_path = recorder.stop()
    assert saved_path.is_file()
    meta_path = saved_path.with_suffix(".meta.json")
    assert meta_path.is_file()

    # Load back using load_recording
    signals, meta = load_recording(saved_path)
    assert meta is not None
    assert meta.experiment_name == "unit_test_run"
    assert meta.condition == "walking"
    assert meta.target_distance_m == 1.5
    assert len(signals["raw_adc"]) == 10
    assert signals["raw_adc"][0] == 12000
    assert signals["raw_adc"][9] == 12045
    assert bool(signals["firmware_motion"][8]) is True
    assert bool(signals["ground_truth_motion"][6]) is True
