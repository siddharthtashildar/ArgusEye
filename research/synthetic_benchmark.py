"""ARGUS-EYE Synthetic Benchmark Generator.
Generates physics-grounded Doppler radar test scenarios with verified ground truth annotations.
Clearly labeled as synthetic for deterministic regression testing and algorithm evaluation.
"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Any, Tuple

import numpy as np

from .recorder import ExperimentMetadata, CSV_COLUMNS
from .spectral_analysis import velocity_to_doppler


def generate_benchmark_dataset(
    scenario: str = "walking_cross_fov",
    duration_s: float = 60.0,
    fs: float = 200.0,
    seed: int = 42,
) -> Tuple[Dict[str, np.ndarray], ExperimentMetadata]:
    """Generate a realistic synthetic Doppler radar dataset with ground truth.
    
    Scenarios:
    - 'stationary_quiet': 60s stationary room with thermal noise, drift, and 50Hz mains hum.
    - 'hand_movement_repeated': 4 discrete hand gestures (20-35 Hz Doppler).
    - 'walking_cross_fov': 3 walking passes across beam pattern (60-85 Hz Doppler).
    - 'walking_towards_away': Walking towards and away with 1/R^2 amplitude modulation.
    - 'impulse_noise_stress': Stationary scene with brief impulse glitches to test noise rejection.
    """
    rng = np.random.default_rng(seed)
    n = int(duration_s * fs)
    t = np.arange(n) / fs

    # Base sensor parameters
    dc_baseline = 12500.0 + 35.0 * np.sin(2.0 * np.pi * 0.02 * t) + 15.0 * (t / duration_s)
    thermal_noise = rng.normal(0.0, 10.0, n)
    mains_hum = 6.0 * np.sin(2.0 * np.pi * 50.0 * t)

    ac_signal = thermal_noise + mains_hum
    ground_truth = np.zeros(n, dtype=bool)

    if scenario == "stationary_quiet":
        # Pure quiet scene, 0 motion events
        pass

    elif scenario == "hand_movement_repeated":
        # 4 hand wave bursts at t = 10s, 22s, 35s, 48s
        event_times = [10.0, 22.0, 35.0, 48.0]
        event_dur = 1.8
        for ev_start in event_times:
            ev_end = ev_start + event_dur
            mask = (t >= ev_start) & (t <= ev_end)
            ground_truth[mask] = True
            t_rel = t[mask] - ev_start
            # Hand wave creates Doppler around 28 Hz with smooth Hanning envelope
            doppler_freq = 28.0 + 4.0 * np.sin(2.0 * np.pi * 1.5 * t_rel)
            phase = 2.0 * np.pi * doppler_freq * t_rel
            window = np.sin(np.pi * t_rel / event_dur) ** 2
            ac_signal[mask] += 260.0 * window * np.sin(phase)

    elif scenario == "walking_cross_fov":
        # 3 walking passes at t = 12s, 28s, 44s
        event_times = [12.0, 28.0, 44.0]
        event_dur = 2.6
        for ev_start in event_times:
            ev_end = ev_start + event_dur
            mask = (t >= ev_start) & (t <= ev_end)
            ground_truth[mask] = True
            t_rel = t[mask] - ev_start
            # Walking Doppler around 70 Hz (approx 1.0 m/s walking speed)
            doppler_freq = 72.0 + 5.0 * np.sin(2.0 * np.pi * 1.8 * t_rel)
            phase = 2.0 * np.pi * doppler_freq * t_rel
            # Antenna beam pattern envelope (cosine squared)
            window = np.sin(np.pi * t_rel / event_dur) ** 2
            ac_signal[mask] += 480.0 * window * np.sin(phase)

    elif scenario == "walking_towards_away":
        # 2 events: approaching at t = 15s (increasing amplitude), departing at t = 38s
        approaching_mask = (t >= 15.0) & (t <= 18.5)
        ground_truth[approaching_mask] = True
        t_app = t[approaching_mask] - 15.0
        # Doppler ~75 Hz, amplitude swells as target nears radar
        amp_app = 100.0 + 380.0 * (t_app / 3.5)
        ac_signal[approaching_mask] += amp_app * np.sin(2.0 * np.pi * 75.0 * t_app)

        departing_mask = (t >= 38.0) & (t <= 41.5)
        ground_truth[departing_mask] = True
        t_dep = t[departing_mask] - 38.0
        amp_dep = 480.0 * (1.0 - t_dep / 4.0) + 80.0
        ac_signal[departing_mask] += amp_dep * np.sin(2.0 * np.pi * 70.0 * t_dep)

    elif scenario == "impulse_noise_stress":
        # 3 isolated sharp impulse spikes at t = 15.0s, 30.0s, 45.0s (1 sample each)
        for spike_time in [15.0, 30.0, 45.0]:
            idx = int(spike_time * fs)
            if 0 <= idx < n:
                ac_signal[idx] += 600.0  # Big glitch, should NOT trigger confirmation filter!

    raw_adc = np.clip(dc_baseline + ac_signal, -32768, 32767).astype(np.int16)

    metadata = ExperimentMetadata(
        session_id=f"SYNTH_{scenario.upper()}_{seed}",
        experiment_name=f"Synthetic Benchmark: {scenario}",
        condition=scenario,
        notes="Generated synthetic dataset with exact ground truth for automated testing",
        device="SYNTHETIC_DOPPLER_MODEL_HB100_10.525GHZ",
        nominal_sample_rate_hz=fs,
        measured_sample_rate_hz=fs,
        total_samples=n,
        duration_seconds=round(duration_s, 2),
        extra_attributes={"is_synthetic": True, "seed": seed, "scenario": scenario},
    )

    signals = {
        "elapsed_s": t,
        "raw_adc": raw_adc.astype(float),
        "baseline_adc": dc_baseline,
        "ac_signal": ac_signal,
        "ground_truth_motion": ground_truth,
    }

    return signals, metadata


def save_synthetic_dataset(
    output_dir: str | Path,
    scenario: str = "walking_cross_fov",
    duration_s: float = 60.0,
    fs: float = 200.0,
    seed: int = 42,
) -> Tuple[Path, Path]:
    """Generate and save synthetic dataset to CSV and JSON metadata."""
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    signals, meta = generate_benchmark_dataset(scenario=scenario, duration_s=duration_s, fs=fs, seed=seed)

    csv_path = out_dir / f"benchmark_{scenario}.csv"
    meta_path = csv_path.with_suffix(".meta.json")

    # Write CSV
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        n = len(signals["elapsed_s"])
        for i in range(n):
            writer.writerow([
                f"2026-10-24T12:00:{signals['elapsed_s'][i]:06.3f}",
                round(float(signals["elapsed_s"][i]), 4),
                i + 1,
                int(signals["elapsed_s"][i] * 1_000_000),
                int(signals["raw_adc"][i]),
                int(signals["baseline_adc"][i]),
                int(signals["ac_signal"][i]),
                0,  # firmware_motion placeholder
                "", # filtered_signal
                "", # envelope
                "", # noise_floor
                "", # active_threshold
                1 if signals["ground_truth_motion"][i] else 0,
            ])

    # Write JSON metadata
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(asdict(meta), f, indent=2)

    return csv_path, meta_path
