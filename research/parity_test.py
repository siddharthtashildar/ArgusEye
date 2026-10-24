"""ARGUS-EYE Embedded vs Offline DSP Parity Simulator.
Implements the exact bit-level / formula-level equations of src/radar_dsp.cpp
to ensure verifiable mathematical equivalence between firmware and research tools.
"""
from __future__ import annotations

from typing import List, Dict, Any
import numpy as np


class EmbeddedDSPModel:
    """Exact software clone of C++ RadarDSP (src/radar_dsp.cpp)."""
    def __init__(
        self,
        detector_mode: int = 1,
        trigger_threshold: int = 120,
        release_ratio: float = 0.65,
        legacy_deadband: int = 50,
        confirm_samples: int = 3,
        hold_samples: int = 30,
    ):
        self.detector_mode = detector_mode
        self.trigger_threshold = trigger_threshold
        self.release_threshold = int(trigger_threshold * release_ratio)
        self.legacy_deadband = legacy_deadband
        self.confirm_samples = confirm_samples
        self.hold_samples = hold_samples

        self.dynamic_baseline = 0.0
        self.baseline_initialized = False

        self.hpf_x_prev = 0.0
        self.hpf_y_prev = 0.0
        self.lpf_y_prev = 0.0

        self.envelope = 0.0
        self.noise_floor = 15.0

        self.above_counter = 0
        self.hold_counter = 0
        self.adaptive_active = False
        self.legacy_active = False

        self.sample_index = 0
        self.event_count = 0
        self.peak_signal = 0
        self.prev_selected_motion = False

    def process_sample(self, raw_adc: int, timestamp_us: int, delta_us: int) -> Dict[str, Any]:
        self.sample_index += 1

        # 1. Dynamic Baseline Tracking
        if not self.baseline_initialized:
            self.dynamic_baseline = float(raw_adc)
            self.baseline_initialized = True
            self.hpf_x_prev = float(raw_adc)
        else:
            self.dynamic_baseline = (self.dynamic_baseline * 0.99) + (float(raw_adc) * 0.01)

        baseline_int = int(round(self.dynamic_baseline))
        ac_signal = raw_adc - baseline_int

        # 2. Legacy Detector
        legacy_sig = ac_signal
        if abs(legacy_sig) < self.legacy_deadband:
            legacy_sig = 0
        self.legacy_active = abs(legacy_sig) > self.trigger_threshold

        # 3. Digital Bandpass Filter
        alpha_hp = 0.888
        raw_f = float(raw_adc)
        hpf_y = alpha_hp * (self.hpf_y_prev + raw_f - self.hpf_x_prev)
        self.hpf_x_prev = raw_f
        self.hpf_y_prev = hpf_y

        beta_lp = 0.715
        lpf_y = self.lpf_y_prev + beta_lp * (hpf_y - self.lpf_y_prev)
        self.lpf_y_prev = lpf_y
        filtered_int = int(round(lpf_y))

        # 4. Envelope Follower
        mag = abs(lpf_y)
        if mag > self.envelope:
            self.envelope = 0.35 * mag + 0.65 * self.envelope
        else:
            self.envelope = 0.05 * mag + 0.95 * self.envelope
        envelope_int = int(round(self.envelope))

        # 5. Online Noise Tracking
        if not self.adaptive_active and self.hold_counter == 0:
            self.noise_floor = 0.998 * self.noise_floor + 0.002 * self.envelope
            if self.noise_floor < 3.0:
                self.noise_floor = 3.0

        # 6. Adaptive Threshold Calculation
        dynamic_trigger = self.trigger_threshold
        noise_margin = int(round(self.noise_floor * 2.0))
        if dynamic_trigger < noise_margin:
            dynamic_trigger = noise_margin
        dynamic_release = int(round(dynamic_trigger * 0.65))
        if dynamic_release < int(round(self.noise_floor)):
            dynamic_release = int(round(self.noise_floor))

        # 7. Hysteresis & Confirmation
        if not self.adaptive_active:
            if self.envelope >= dynamic_trigger:
                self.above_counter += 1
                if self.above_counter >= self.confirm_samples:
                    self.adaptive_active = True
                    self.hold_counter = self.hold_samples
                    self.above_counter = 0
            else:
                self.above_counter = 0
        else:
            if self.envelope >= dynamic_release:
                self.hold_counter = self.hold_samples
            else:
                if self.hold_counter > 0:
                    self.hold_counter -= 1
                else:
                    self.adaptive_active = False
                    self.above_counter = 0

        # 8. Selection
        selected_motion = self.adaptive_active if self.detector_mode == 1 else self.legacy_active

        abs_sig = abs(ac_signal)
        if abs_sig > self.peak_signal:
            self.peak_signal = abs_sig

        if selected_motion and not self.prev_selected_motion:
            self.event_count += 1
        self.prev_selected_motion = selected_motion

        return {
            "sample_index": self.sample_index,
            "raw_adc": raw_adc,
            "baseline_adc": baseline_int,
            "ac_signal": ac_signal,
            "filtered_signal": filtered_int,
            "envelope": envelope_int,
            "noise_floor": int(round(self.noise_floor)),
            "trigger_threshold": dynamic_trigger,
            "release_threshold": dynamic_release,
            "legacy_motion": self.legacy_active,
            "adaptive_motion": self.adaptive_active,
            "selected_motion": selected_motion,
        }
