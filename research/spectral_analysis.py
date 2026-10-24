"""ARGUS-EYE Spectral Analysis Module.
Provides Welch Power Spectral Density, Spectrogram (STFT), and Doppler velocity estimation.
"""
from __future__ import annotations

from typing import Tuple, Dict, Optional
import numpy as np
from scipy import signal as sp_signal

# HB100 Carrier Frequency: 10.525 GHz
HB100_CARRIER_FREQ_HZ = 10.525e9
SPEED_OF_LIGHT_M_S = 299792458.0
# Doppler scale factor: fd = 2 * v * f0 / c => fd / v = 70.215 Hz per (m/s)
DOPPLER_SCALE_HZ_PER_M_S = (2.0 * HB100_CARRIER_FREQ_HZ) / SPEED_OF_LIGHT_M_S


def doppler_to_velocity(fd_hz: float | np.ndarray) -> float | np.ndarray:
    """Convert Doppler frequency shift (Hz) to radial velocity (m/s).
    fd = 2 * v * f0 / c  =>  v = fd * c / (2 * f0)
    At 10.525 GHz, 1 m/s produces ~70.22 Hz Doppler shift.
    """
    return fd_hz / DOPPLER_SCALE_HZ_PER_M_S


def velocity_to_doppler(v_m_s: float | np.ndarray) -> float | np.ndarray:
    """Convert radial velocity (m/s) to Doppler frequency shift (Hz)."""
    return v_m_s * DOPPLER_SCALE_HZ_PER_M_S


def compute_welch_psd(
    signal_data: np.ndarray,
    fs: float = 200.0,
    nperseg: int = 256,
    noverlap: Optional[int] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute Welch Power Spectral Density estimate.
    
    Returns:
        freqs: Frequency axis (Hz)
        psd_db: Power spectral density in dB (10 * log10(Pxx))
    """
    if len(signal_data) < 16:
        return np.array([0.0]), np.array([0.0])
    
    seg_len = min(len(signal_data), nperseg)
    if noverlap is None:
        noverlap = seg_len // 2

    freqs, pxx = sp_signal.welch(
        signal_data,
        fs=fs,
        window="hann",
        nperseg=seg_len,
        noverlap=noverlap,
        scaling="density",
    )
    # Convert to dB relative to 1 ADC count^2 / Hz
    psd_db = 10.0 * np.log10(np.maximum(pxx, 1e-12))
    return freqs, psd_db


def compute_spectrogram(
    signal_data: np.ndarray,
    fs: float = 200.0,
    nperseg: int = 128,
    noverlap: int = 96,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute Short-Time Fourier Transform (STFT) Spectrogram.
    
    Returns:
        times: Time array (seconds)
        freqs: Frequency array (Hz)
        sxx_db: Spectrogram power in dB
    """
    if len(signal_data) < 32:
        return np.array([0.0]), np.array([0.0]), np.zeros((1, 1))

    seg_len = min(len(signal_data), nperseg)
    overlap = min(seg_len - 1, noverlap)

    freqs, times, sxx = sp_signal.spectrogram(
        signal_data,
        fs=fs,
        window="hann",
        nperseg=seg_len,
        noverlap=overlap,
        scaling="density",
        mode="psd",
    )
    sxx_db = 10.0 * np.log10(np.maximum(sxx, 1e-12))
    return times, freqs, sxx_db


def estimate_peak_velocity_profile(
    times: np.ndarray,
    freqs: np.ndarray,
    sxx_db: np.ndarray,
    min_freq_hz: float = 5.0,
    snr_thresh_db: float = 12.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Estimate Doppler peak frequency and radial velocity over time."""
    valid_freq_mask = freqs >= min_freq_hz
    sub_freqs = freqs[valid_freq_mask]
    sub_sxx = sxx_db[valid_freq_mask, :]

    if len(sub_freqs) == 0:
        return np.zeros_like(times), np.zeros_like(times)

    noise_floor_db = float(np.percentile(sub_sxx, 15))
    peak_freqs = np.zeros(len(times))

    for col in range(len(times)):
        col_power = sub_sxx[:, col]
        max_idx = np.argmax(col_power)
        if col_power[max_idx] >= (noise_floor_db + snr_thresh_db):
            peak_freqs[col] = sub_freqs[max_idx]
        else:
            peak_freqs[col] = 0.0

    peak_velocities = doppler_to_velocity(peak_freqs)
    return peak_freqs, peak_velocities
