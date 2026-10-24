"""ARGUS-EYE Signal Processing Research Pipeline.
Modular implementation of filtering, baseline tracking, envelope estimation,
adaptive noise-aware detection, and event processing.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any

import numpy as np
from scipy import signal as sp_signal


def moving_average(data: np.ndarray, window_size: int = 5) -> np.ndarray:
    """Compute moving-average smoothing over 1D numpy array with boundary preservation."""
    if window_size <= 1 or len(data) < window_size:
        return np.asarray(data, dtype=float).copy()
    from scipy.ndimage import uniform_filter1d
    return uniform_filter1d(np.asarray(data, dtype=float), size=window_size, mode="nearest")


def exponential_smoothing(data: np.ndarray, alpha: float = 0.05) -> np.ndarray:
    """Causal exponential moving average (EMA) smoothing."""
    alpha = max(0.0001, min(1.0, alpha))
    out = np.empty_like(data, dtype=float)
    if len(data) == 0:
        return out
    out[0] = data[0]
    for i in range(1, len(data)):
        out[i] = alpha * data[i] + (1.0 - alpha) * out[i - 1]
    return out


def butter_bandpass_filter(
    data: np.ndarray,
    lowcut: float = 5.0,
    highcut: float = 80.0,
    fs: float = 200.0,
    order: int = 2,
    causal: bool = True,
) -> np.ndarray:
    """Digital Butterworth band-pass filter with Nyquist validation.
    
    If highcut exceeds Nyquist (fs/2), it is safely constrained to 0.45 * fs.
    Supports causal mode (lfilter) and zero-phase mode (sosfiltfilt).
    """
    if len(data) < 4:
        return np.asarray(data, dtype=float).copy()

    nyquist = 0.5 * fs
    if nyquist <= 0:
        return np.asarray(data, dtype=float).copy()

    # Validate and constrain cutoffs relative to Nyquist
    low = max(0.1, min(lowcut, nyquist * 0.9))
    high = min(highcut, nyquist * 0.95)
    if low >= high:
        low = high * 0.1

    low_norm = low / nyquist
    high_norm = high / nyquist

    sos = sp_signal.butter(order, [low_norm, high_norm], btype="bandpass", output="sos")

    if causal:
        # Causal filtering matches embedded real-time execution
        zi = sp_signal.sosfilt_zi(sos) * data[0]
        filtered, _ = sp_signal.sosfilt(sos, data, zi=zi)
        return filtered
    else:
        # Zero-phase forward-backward filtering for clean offline analysis
        return sp_signal.sosfiltfilt(sos, data)


def compute_envelope_hilbert(data: np.ndarray) -> np.ndarray:
    """Compute offline analytic signal envelope using the Hilbert transform."""
    if len(data) < 4:
        return np.abs(data).astype(float)
    analytic = sp_signal.hilbert(data)
    return np.abs(analytic)


def compute_envelope_causal(
    data: np.ndarray,
    attack: float = 0.35,
    decay: float = 0.05,
) -> np.ndarray:
    """Causal rectified leaky peak envelope follower matching embedded firmware."""
    out = np.empty_like(data, dtype=float)
    if len(data) == 0:
        return out
    
    current_env = float(abs(data[0]))
    out[0] = current_env
    for i in range(1, len(data)):
        mag = float(abs(data[i]))
        if mag > current_env:
            current_env = attack * mag + (1.0 - attack) * current_env
        else:
            current_env = decay * mag + (1.0 - decay) * current_env
        out[i] = current_env
    return out


def estimate_baseline(
    raw: np.ndarray,
    method: str = "ema",
    alpha: float = 0.01,
) -> np.ndarray:
    """Estimate dynamic DC baseline from raw ADC samples."""
    if method == "ema":
        return exponential_smoothing(raw, alpha=alpha)
    elif method == "median":
        from scipy.ndimage import median_filter
        return median_filter(raw, size=min(len(raw) if len(raw) % 2 == 1 else len(raw) - 1, 101))
    else:
        return np.full_like(raw, np.mean(raw), dtype=float)


def estimate_noise_floor(
    envelope: np.ndarray,
    percentile: float = 20.0,
    min_floor: float = 5.0,
) -> float:
    """Estimate quiet background noise floor from envelope statistics."""
    if len(envelope) == 0:
        return min_floor
    p_val = float(np.percentile(envelope, percentile))
    return max(min_floor, p_val)


def detect_motion_legacy(
    raw: np.ndarray,
    baseline: np.ndarray,
    deadband: int = 50,
    threshold: int = 30,
) -> np.ndarray:
    """Original reference firmware detector:
    sig = raw - baseline
    if abs(sig) < deadband: sig = 0
    motion = abs(sig) > threshold
    """
    sig = raw.astype(float) - baseline.astype(float)
    sig_zeroed = np.where(np.abs(sig) < deadband, 0.0, sig)
    return (np.abs(sig_zeroed) > threshold).astype(bool)


def detect_motion_adaptive(
    envelope: np.ndarray,
    noise_floor: float,
    min_thresh: int = 60,
    snr_multiplier: float = 2.5,
    release_ratio: float = 0.65,
    confirm_samples: int = 3,
    hold_samples: int = 30,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Causal adaptive noise-aware detector with hysteresis, confirmation, and hold.
    
    Returns:
        motion_active: bool array of detected motion states
        trigger_thresholds: float array of active trigger levels
        release_thresholds: float array of active release levels
    """
    n = len(envelope)
    motion = np.zeros(n, dtype=bool)
    trig_arr = np.zeros(n, dtype=float)
    rel_arr = np.zeros(n, dtype=float)

    trigger_thresh = max(float(min_thresh), noise_floor * snr_multiplier + 10.0)
    release_thresh = max(noise_floor, trigger_thresh * release_ratio)

    is_active = False
    above_cnt = 0
    hold_cnt = 0

    for i in range(n):
        val = envelope[i]
        trig_arr[i] = trigger_thresh
        rel_arr[i] = release_thresh

        if not is_active:
            if val >= trigger_thresh:
                above_cnt += 1
                if above_cnt >= confirm_samples:
                    is_active = True
                    hold_cnt = hold_samples
                    above_cnt = 0
            else:
                above_cnt = 0
        else:
            if val >= release_thresh:
                hold_cnt = hold_samples
            else:
                if hold_cnt > 0:
                    hold_cnt -= 1
                else:
                    is_active = False
                    above_cnt = 0

        motion[i] = is_active

    return motion, trig_arr, rel_arr


@dataclass
class MotionEvent:
    start_time: float
    end_time: float
    duration: float
    peak_amplitude: float
    start_idx: int
    end_idx: int


def extract_events(
    motion: np.ndarray,
    timestamps: np.ndarray,
    signal_magnitude: np.ndarray,
) -> List[MotionEvent]:
    """Extract discrete start/end motion event intervals from a boolean motion array."""
    events: List[MotionEvent] = []
    if len(motion) == 0 or len(timestamps) == 0:
        return events

    in_event = False
    start_idx = 0

    for i in range(len(motion)):
        if motion[i] and not in_event:
            in_event = True
            start_idx = i
        elif not motion[i] and in_event:
            in_event = False
            end_idx = i - 1
            t_start = float(timestamps[start_idx])
            t_end = float(timestamps[end_idx])
            peak = float(np.max(signal_magnitude[start_idx : end_idx + 1])) if end_idx >= start_idx else 0.0
            events.append(MotionEvent(
                start_time=t_start,
                end_time=t_end,
                duration=max(0.0, t_end - t_start),
                peak_amplitude=peak,
                start_idx=start_idx,
                end_idx=end_idx,
            ))

    if in_event:
        end_idx = len(motion) - 1
        t_start = float(timestamps[start_idx])
        t_end = float(timestamps[end_idx])
        peak = float(np.max(signal_magnitude[start_idx : end_idx + 1]))
        events.append(MotionEvent(
            start_time=t_start,
            end_time=t_end,
            duration=max(0.0, t_end - t_start),
            peak_amplitude=peak,
            start_idx=start_idx,
            end_idx=end_idx,
        ))

    return events


def merge_events(events: List[MotionEvent], max_gap_s: float = 0.25) -> List[MotionEvent]:
    """Merge closely-spaced motion events within max_gap_s to reject Doppler fluttering."""
    if not events:
        return []

    merged: List[MotionEvent] = [events[0]]
    for ev in events[1:]:
        prev = merged[-1]
        gap = ev.start_time - prev.end_time
        if gap <= max_gap_s:
            # Merge ev into prev
            merged[-1] = MotionEvent(
                start_time=prev.start_time,
                end_time=ev.end_time,
                duration=ev.end_time - prev.start_time,
                peak_amplitude=max(prev.peak_amplitude, ev.peak_amplitude),
                start_idx=prev.start_idx,
                end_idx=ev.end_idx,
            )
        else:
            merged.append(ev)

    return merged


class RadarDSPPipeline:
    """Unified Research Pipeline for Doppler Radar Signal Processing.
    Executes multiple filtering and detector algorithms on raw recordings for comparison.
    """
    def __init__(
        self,
        fs: float = 200.0,
        bpf_low: float = 5.0,
        bpf_high: float = 80.0,
        min_threshold: int = 60,
        legacy_deadband: int = 50,
        legacy_threshold: int = 30,
        confirm_samples: int = 3,
        hold_samples: int = 30,
    ):
        self.fs = fs
        self.bpf_low = bpf_low
        self.bpf_high = bpf_high
        self.min_threshold = min_threshold
        self.legacy_deadband = legacy_deadband
        self.legacy_threshold = legacy_threshold
        self.confirm_samples = confirm_samples
        self.hold_samples = hold_samples

    def run(
        self,
        raw_adc: np.ndarray,
        timestamps_s: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """Process a raw ADC recording through all candidate stages."""
        n = len(raw_adc)
        if timestamps_s is None:
            timestamps_s = np.arange(n) / self.fs

        # 1. Baseline estimation
        baseline_ema = estimate_baseline(raw_adc, method="ema", alpha=0.01)
        ac_signal = raw_adc - baseline_ema

        # 2. Moving average and exponential smoothing
        signal_ma = moving_average(ac_signal, window_size=5)
        signal_ema = exponential_smoothing(ac_signal, alpha=0.1)

        # 3. Digital bandpass filter (causal for parity, zero-phase for benchmark)
        signal_bpf_causal = butter_bandpass_filter(
            ac_signal, lowcut=self.bpf_low, highcut=self.bpf_high, fs=self.fs, causal=True
        )
        signal_bpf_offline = butter_bandpass_filter(
            ac_signal, lowcut=self.bpf_low, highcut=self.bpf_high, fs=self.fs, causal=False
        )

        # 4. Envelopes
        envelope_causal = compute_envelope_causal(signal_bpf_causal, attack=0.35, decay=0.05)
        envelope_hilbert = compute_envelope_hilbert(signal_bpf_offline)

        # 5. Noise floor
        noise_floor = estimate_noise_floor(envelope_causal, percentile=20.0)

        # 6. Detectors
        # Candidate 1: Legacy reference detector
        legacy_motion = detect_motion_legacy(
            raw_adc, baseline_ema, deadband=self.legacy_deadband, threshold=self.legacy_threshold
        )

        # Candidate 2: Adaptive causal detector
        adaptive_motion, trig_arr, rel_arr = detect_motion_adaptive(
            envelope_causal,
            noise_floor=noise_floor,
            min_thresh=self.min_threshold,
            confirm_samples=self.confirm_samples,
            hold_samples=self.hold_samples,
        )

        # 7. Extract discrete events
        legacy_events = merge_events(extract_events(legacy_motion, timestamps_s, np.abs(ac_signal)))
        adaptive_events = merge_events(extract_events(adaptive_motion, timestamps_s, envelope_causal))

        return {
            "timestamps_s": timestamps_s,
            "raw_adc": raw_adc,
            "baseline_ema": baseline_ema,
            "ac_signal": ac_signal,
            "signal_ma": signal_ma,
            "signal_ema": signal_ema,
            "signal_bpf_causal": signal_bpf_causal,
            "signal_bpf_offline": signal_bpf_offline,
            "envelope_causal": envelope_causal,
            "envelope_hilbert": envelope_hilbert,
            "noise_floor": noise_floor,
            "trigger_threshold": trig_arr,
            "release_threshold": rel_arr,
            "legacy_motion": legacy_motion,
            "adaptive_motion": adaptive_motion,
            "legacy_events": legacy_events,
            "adaptive_events": adaptive_events,
        }
