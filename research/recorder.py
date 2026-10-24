"""ARGUS-EYE Data Recording and Dataset Management.
Handles CSV telemetry recording with experiment metadata and offline replay loading.
"""
from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import numpy as np

from .protocol import TelemetryPacket


@dataclass
class ExperimentMetadata:
    session_id: str
    experiment_name: str
    condition: str
    notes: str = ""
    target_distance_m: Optional[float] = None
    target_angle_deg: Optional[float] = None
    device: str = "ESP32-S3 + HB100 (10.525GHz) + LM358 + ADS1115"
    nominal_sample_rate_hz: float = 200.0
    measured_sample_rate_hz: float = 0.0
    start_time_iso: str = ""
    stop_time_iso: str = ""
    total_samples: int = 0
    duration_seconds: float = 0.0
    extra_attributes: Dict[str, Any] = field(default_factory=dict)


CSV_COLUMNS = [
    "timestamp_iso",
    "elapsed_s",
    "sample_idx",
    "device_t_us",
    "raw_adc",
    "baseline_adc",
    "ac_signal",
    "firmware_motion",
    "filtered_signal",
    "envelope",
    "noise_floor",
    "active_threshold",
    "ground_truth_motion",
]


class SessionRecorder:
    """Manages active file writing for telemetry datasets with metadata tracking."""
    def __init__(self):
        self.is_recording = False
        self.csv_path: Optional[Path] = None
        self.meta_path: Optional[Path] = None
        self._file = None
        self._writer = None
        self.metadata: Optional[ExperimentMetadata] = None
        self.start_monotonic: float = 0.0
        self.sample_count: int = 0
        self._timestamps_monotonic: List[float] = []

    def start(
        self,
        output_csv_path: str | Path,
        experiment_name: str = "experiment",
        condition: str = "general",
        notes: str = "",
        target_distance_m: Optional[float] = None,
        target_angle_deg: Optional[float] = None,
        nominal_sample_rate_hz: float = 200.0,
    ) -> Path:
        self.csv_path = Path(output_csv_path).resolve()
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.csv_path.with_suffix(".meta.json")

        session_id = f"AE_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        start_iso = datetime.now().isoformat(timespec="milliseconds")

        self.metadata = ExperimentMetadata(
            session_id=session_id,
            experiment_name=experiment_name,
            condition=condition,
            notes=notes,
            target_distance_m=target_distance_m,
            target_angle_deg=target_angle_deg,
            nominal_sample_rate_hz=nominal_sample_rate_hz,
            start_time_iso=start_iso,
        )

        self._file = open(self.csv_path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(CSV_COLUMNS)

        self.start_monotonic = time.monotonic()
        self.sample_count = 0
        self._timestamps_monotonic.clear()
        self.is_recording = True
        return self.csv_path

    def write_sample(self, packet: TelemetryPacket, ground_truth_motion: int = 0) -> None:
        if not self.is_recording or self._writer is None:
            return

        now_mono = time.monotonic()
        elapsed_s = round(now_mono - self.start_monotonic, 4)
        self.sample_count += 1
        self._timestamps_monotonic.append(now_mono)

        row = [
            datetime.now().isoformat(timespec="milliseconds"),
            elapsed_s,
            packet.seq if packet.seq is not None else self.sample_count,
            packet.t_us if packet.t_us is not None else "",
            packet.raw,
            packet.baseline,
            packet.signal,
            1 if packet.firmware_motion else 0,
            packet.filtered if packet.filtered is not None else "",
            packet.envelope if packet.envelope is not None else "",
            packet.noise_floor if packet.noise_floor is not None else "",
            packet.threshold if packet.threshold is not None else "",
            ground_truth_motion,
        ]
        self._writer.writerow(row)

    def stop(self) -> Optional[Path]:
        if not self.is_recording:
            return None

        self.is_recording = False
        duration_s = max(0.001, time.monotonic() - self.start_monotonic)

        if self._file:
            self._file.flush()
            self._file.close()
            self._file = None
            self._writer = None

        if self.metadata:
            self.metadata.stop_time_iso = datetime.now().isoformat(timespec="milliseconds")
            self.metadata.total_samples = self.sample_count
            self.metadata.duration_seconds = round(duration_s, 3)
            if len(self._timestamps_monotonic) > 1:
                dt_actual = self._timestamps_monotonic[-1] - self._timestamps_monotonic[0]
                if dt_actual > 0:
                    self.metadata.measured_sample_rate_hz = round(
                        (len(self._timestamps_monotonic) - 1) / dt_actual, 2
                    )

            if self.meta_path:
                with open(self.meta_path, "w", encoding="utf-8") as f:
                    json.dump(asdict(self.metadata), f, indent=2)

        return self.csv_path


def load_recording(csv_path: str | Path) -> Tuple[Dict[str, np.ndarray], Optional[ExperimentMetadata]]:
    """Load a saved radar CSV session and associated metadata JSON file.
    
    Returns:
        signals: dict of numpy arrays for each telemetry column
        metadata: ExperimentMetadata object if companion JSON exists, else None
    """
    path = Path(csv_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Recording CSV not found: {path}")

    meta: Optional[ExperimentMetadata] = None
    meta_path = path.with_suffix(".meta.json")
    if meta_path.is_file():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta_dict = json.load(f)
                meta = ExperimentMetadata(**meta_dict)
        except Exception:
            pass

    # Read CSV
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return {}, meta

    n = len(rows)
    elapsed_s = np.zeros(n, dtype=float)
    raw_adc = np.zeros(n, dtype=float)
    baseline_adc = np.zeros(n, dtype=float)
    ac_signal = np.zeros(n, dtype=float)
    firmware_motion = np.zeros(n, dtype=bool)
    ground_truth = np.zeros(n, dtype=bool)

    has_filtered = "filtered_signal" in rows[0] and bool(rows[0]["filtered_signal"])
    has_envelope = "envelope" in rows[0] and bool(rows[0]["envelope"])
    filtered_signal = np.zeros(n, dtype=float) if has_filtered else None
    envelope = np.zeros(n, dtype=float) if has_envelope else None

    for i, r in enumerate(rows):
        elapsed_s[i] = float(r.get("elapsed_s", i * 0.005) or (i * 0.005))
        raw_adc[i] = float(r.get("raw_adc", 0.0) or 0.0)
        baseline_adc[i] = float(r.get("baseline_adc", 0.0) or 0.0)
        ac_signal[i] = float(r.get("ac_signal", raw_adc[i] - baseline_adc[i]) or 0.0)
        firmware_motion[i] = bool(int(r.get("firmware_motion", "0") or 0))
        ground_truth[i] = bool(int(r.get("ground_truth_motion", "0") or 0))
        if has_filtered and filtered_signal is not None:
            val = r.get("filtered_signal")
            filtered_signal[i] = float(val) if val else 0.0
        if has_envelope and envelope is not None:
            val = r.get("envelope")
            envelope[i] = float(val) if val else 0.0

    signals = {
        "elapsed_s": elapsed_s,
        "raw_adc": raw_adc,
        "baseline_adc": baseline_adc,
        "ac_signal": ac_signal,
        "firmware_motion": firmware_motion,
        "ground_truth_motion": ground_truth,
    }
    if filtered_signal is not None:
        signals["filtered_signal"] = filtered_signal
    if envelope is not None:
        signals["envelope"] = envelope

    return signals, meta
