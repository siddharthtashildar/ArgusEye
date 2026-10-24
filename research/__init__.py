"""ARGUS-EYE Doppler Radar Signal-Processing & Research Toolkit.
Provides causal & offline filtering, spectral analysis, evaluation, and protocol parsing.
"""

from .protocol import TelemetryPacket, parse_telemetry_line, format_command
from .dsp_pipeline import (
    moving_average,
    exponential_smoothing,
    butter_bandpass_filter,
    compute_envelope_hilbert,
    compute_envelope_causal,
    estimate_noise_floor,
    detect_motion_legacy,
    detect_motion_adaptive,
    RadarDSPPipeline,
)
from .spectral_analysis import compute_welch_psd, compute_spectrogram, doppler_to_velocity
from .evaluation import evaluate_detections, EvaluationResult, match_events
from .recorder import SessionRecorder, load_recording

__all__ = [
    "TelemetryPacket",
    "parse_telemetry_line",
    "format_command",
    "moving_average",
    "exponential_smoothing",
    "butter_bandpass_filter",
    "compute_envelope_hilbert",
    "compute_envelope_causal",
    "estimate_noise_floor",
    "detect_motion_legacy",
    "detect_motion_adaptive",
    "RadarDSPPipeline",
    "compute_welch_psd",
    "compute_spectrogram",
    "doppler_to_velocity",
    "evaluate_detections",
    "EvaluationResult",
    "match_events",
    "SessionRecorder",
    "load_recording",
]
