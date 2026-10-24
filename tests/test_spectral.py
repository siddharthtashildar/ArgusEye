"""Tests for Doppler physics conversions, Welch PSD, and Spectrogram."""
import numpy as np
import pytest
from research.spectral_analysis import (
    doppler_to_velocity,
    velocity_to_doppler,
    compute_welch_psd,
    compute_spectrogram,
    DOPPLER_SCALE_HZ_PER_M_S,
)


def test_doppler_velocity_conversion():
    # At 10.525 GHz, ~70.215 Hz corresponds to 1.0 m/s
    v_1 = doppler_to_velocity(DOPPLER_SCALE_HZ_PER_M_S)
    assert abs(v_1 - 1.0) < 0.001

    fd_back = velocity_to_doppler(1.0)
    assert abs(fd_back - DOPPLER_SCALE_HZ_PER_M_S) < 0.001

    # Human walking at 1.2 m/s -> ~84.26 Hz
    assert abs(velocity_to_doppler(1.2) - 84.26) < 0.1


def test_compute_welch_psd():
    fs = 200.0
    t = np.arange(400) / fs
    # 40 Hz pure tone
    sig = 100.0 * np.sin(2 * np.pi * 40.0 * t)

    freqs, psd_db = compute_welch_psd(sig, fs=fs, nperseg=256)
    assert len(freqs) == len(psd_db)
    # Peak power should occur near 40 Hz
    peak_freq = freqs[np.argmax(psd_db)]
    assert abs(peak_freq - 40.0) < 2.0


def test_compute_spectrogram():
    fs = 200.0
    t = np.arange(400) / fs
    sig = 100.0 * np.sin(2 * np.pi * 50.0 * t)

    times, freqs, sxx_db = compute_spectrogram(sig, fs=fs, nperseg=128, noverlap=96)
    assert len(times) > 0
    assert len(freqs) > 0
    assert sxx_db.shape == (len(freqs), len(times))
