# ARGUS-EYE // Microwave Doppler Radar Intelligence System

**ARGUS-EYE** is a complete, research-oriented 10.525 GHz continuous-wave (CW) Doppler radar motion-detection system. It combines an embedded ESP32-S3 acquisition controller, ADS1115 delta-sigma ADC, LM358 analog amplifier, and a cyberpunk-styled Python engineering console with real-time DSP, Welch PSD, STFT spectrogram analysis, and quantitative performance evaluation.

---

## 1. System Architecture

```text
 [Target in Motion]
        |  10.525 GHz CW Reflection
        v
 [HB100 Radar] ---> [LM358 Preamp (~100x)] ---> [ADS1115 ADC (16-bit, 400kHz I2C)]
                                                           |
                                                           v  Paced 200 Hz Acquisition
                                                   [ESP32-S3 Firmware]
                                                    |-- Dynamic Baseline Tracking (EMA)
                                                    |-- Causal Bandpass Filter (5-80 Hz)
                                                    |-- Leaky Envelope Follower
                                                    |-- Adaptive Hysteresis Detector
                                                    |-- Decoupled TFT (25 Hz) & FPGA UART (10 Hz)
                                                           |
                                                           v  USB Serial (115200 Baud)
                                                   [PC Engineering Console]
                                                    |-- Live Scrolling Waveform & Overlays
                                                    |-- Cadence & Packet Loss Tracker
                                                    |-- Session CSV Recorder + Metadata
                                                    |-- Welch PSD & STFT Spectrogram View
                                                    |-- Quantitative Evaluation Framework
```

---

## 2. Hardware Wiring

### ESP32-S3 to ADS1115 ADC
| ADS1115 Pin | ESP32-S3 Pin | Function |
|---|---|---|
| `VDD` | `3.3V` | Logic & ADC supply |
| `GND` | `GND` | Common Ground |
| `SDA` | `GPIO21` | I2C Data (400 kHz Fast-Mode) |
| `SCL` | `GPIO18` | I2C Clock (400 kHz Fast-Mode) |
| `ADDR` | `GND` | I2C Address `0x48` |
| `A0` | `LM358 Pin 1` | Amplified Doppler IF analog signal |

### HB100 & LM358 Analog Conditioning Chain
- `HB100 VCC` → `ESP32 5V / VIN`
- `HB100 GND` → `GND`
- `HB100 IF` → `LM358 IN+` (Pin 3)
- `LM358 VCC` → `ESP32 3.3V` (Pin 8)
- `LM358 GND` → `GND` (Pin 4)
- `LM358 IN-` (Pin 2) → `GND` via $1\text{ k}\Omega$ ($R_i$)
- `LM358 OUT` (Pin 1) → `LM358 IN-` (Pin 2) via $100\text{ k}\Omega$ ($R_f$) for $\sim 100\times$ AC gain
- `LM358 OUT` (Pin 1) → `ADS1115 A0`

### Display & FPGA Links (Optional / Preserved)
- **ST7789 TFT:** MOSI=`GPIO11`, SCLK=`GPIO12`, CS=`GPIO9`, DC=`GPIO15`, RST=`GPIO14`.
- **FPGA UART:** `GPIO17` (TX) → Nexys A7 `uart_rx_pin` (JB Pin 2) at 9600 baud.

---

## 3. Quick Start

### 3.1 Firmware Build & Flash
Build and flash the firmware to your ESP32-S3 using PlatformIO:

```bash
# Build firmware
pio run

# Upload to ESP32-S3 (COM4 by default in platformio.ini)
pio run --target upload
```

*(If PlatformIO is not on your Windows system PATH, run via `& "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe" run`)*.

### 3.2 Python Environment Setup
```bash
# Install dependencies
pip install -r GUI/requirements.txt
```

### 3.3 Launch PC Dashboard
```bash
python GUI/main.py
```
1. Select your ESP32's COM port (e.g. `COM4`) and `115200` baud.
2. Click **CONNECT ↗**.
3. View live scrolling Doppler traces, dynamic trigger/release thresholds, envelope meter, and sample cadence diagnostics.

---

## 4. Signal Processing & Research Toolkit

The modular Python research toolkit in `research/` provides:
- **Filters:** Moving Average, Exponential Smoothing (EMA), Butterworth Bandpass (5 - 80 Hz with Nyquist constraint checking).
- **Envelopes:** Hilbert transform analytic envelope & causal leaky peak follower.
- **Detectors:**
  - `Legacy Detector`: Baseline EMA + 50 deadband + threshold (reference).
  - `Adaptive Causal Detector`: Background noise floor estimation + adaptive hysteresis (trigger & release) + persistence confirmation filter ($N=3$) + hold-off cooldown.
- **Spectral Tools:** Welch Power Spectral Density (PSD) and STFT Spectrogram with Doppler velocity conversion ($v = f_d / 70.22\text{ m/s}$).

### Run Quantitative Evaluation Benchmark
```bash
python research/run_evaluation.py
```

### Run Automated Test Suite
```bash
python -m pytest -v
```

---

## 5. Serial Protocol

Machine-parseable telemetry streamed over USB serial:
```text
Seq:1042 T_us:5210000 Dt:5000 Raw:12345 Base:12340 Sig:5 Motion:NO Filt:4 Env:6 Noise:12 Thresh:80 Det:1
```
- Fully backward compatible with legacy regular expressions (`Raw:\d+ Base:\d+ Sig:\d+ Motion:(YES|NO)`).
- Bidirectional commands supported:
  - `CMD:SET_THRESH=<val>`: Sets trigger threshold in ADC counts.
  - `CMD:SET_DET=<0|1>`: Sets active detector (`0` = Legacy, `1` = Adaptive).
  - `CMD:CAL`: Initiates 2.5s quiet baseline calibration.
  - `CMD:RESET`: Resets event counters and statistics.

---

## 6. Target Engineering Benchmarks

| Metric | Target Goal | Adaptive Causal Detector | Legacy Baseline Detector |
|---|---|---|---|
| **Precision** | $\ge 90.0\%$ | **$100.0\%$** | $66.7\% - 80.0\%$ |
| **Recall** | $\ge 90.0\%$ | **$100.0\%$** | $100.0\%$ |
| **F1 Score** | $\ge 90.0\%$ | **$100.0\%$** | $80.0\% - 88.9\%$ |
| **False Alarm Rate (Stationary)** | $\le 1.0\text{ / min}$ | **$0.00\text{ / min}$** | $1.00 - 1.14\text{ / min}$ |
| **Median Detection Latency** | $\le 300\text{ ms}$ | **$35\text{ ms}$** *(approach)* | $5\text{ ms}$ *(high false alarm)* |

---

## 7. Known Physical Limitations & Engineering Notes

1. **Continuous-Wave (CW) Limitation:** The HB100 is a single-frequency continuous-wave Doppler radar. It measures **radial target velocity** via Doppler shift, but **does not measure absolute distance or range**.
2. **ADS1115 Sampling Ceiling:** The ADS1115 maximum data rate is 860 SPS. Under 400 kHz I2C, reliable paced single-ended acquisition is bounded at $200 - 250\text{ Hz}$. This yields a Nyquist frequency of $100 - 125\text{ Hz}$, which fully covers human walking and hand motions ($0.1 - 1.5\text{ m/s}$), but will alias ultra-fast sports objects ($> 2.0\text{ m/s}$).
3. **Mains 50/60 Hz Hum:** High analog gain ($\sim 100\times$) in the LM358 stage picks up stray 50/60 Hz magnetic fields. The firmware and Python digital bandpass filters effectively attenuate DC baseline drift and 50 Hz harmonics.

---

## 8. Repository Structure

```text
DopplerRadarSystem/
├── src/
│   ├── main.cpp                  # Decoupled paced acquisition & telemetry firmware
│   ├── radar_dsp.cpp             # Causal embedded DSP: baseline, BPF, envelope, hysteresis
│   └── serial_protocol.cpp       # Serial packet serializer & command parser
├── include/
│   ├── radar_config.h            # Hardware pinouts, default thresholds, and timings
│   ├── radar_dsp.h               # Embedded DSP class declaration
│   └── serial_protocol.h         # Serial protocol interface
├── research/
│   ├── dsp_pipeline.py           # Research filtering, envelopes, baseline, adaptive detectors
│   ├── spectral_analysis.py      # Welch PSD, STFT Spectrogram, Doppler velocity conversion
│   ├── protocol.py               # Telemetry parser, packet loss & cadence tracker
│   ├── recorder.py               # CSV recording manager with metadata tracking
│   ├── evaluation.py             # Quantitative evaluation framework (Precision, Recall, FAR, Latency)
│   ├── synthetic_benchmark.py    # Physics-grounded benchmark generator with ground truth
│   ├── parity_test.py            # Mathematical parity verifier between C++ & Python
│   └── run_evaluation.py         # Evaluation benchmark runner CLI
├── GUI/
│   ├── main.py                   # Cyberpunk engineering console with live plots & spectral dialog
│   └── requirements.txt          # Python dependencies
├── tests/
│   ├── test_protocol.py          # Unit tests for protocol parsing & cadence tracking
│   ├── test_dsp_pipeline.py      # Unit tests for digital filters, envelopes, & detectors
│   ├── test_spectral.py          # Unit tests for PSD, spectrogram, & Doppler equations
│   ├── test_evaluation.py        # Unit tests for event matching & evaluation metrics
│   ├── test_recorder.py          # Unit tests for dataset recording & replaying
│   ├── test_parity.py            # Parity tests verifying C++ and Python equivalence
│   └── test_dashboard_smoke.py   # Headless smoke test for PySide6 console
├── docs/
│   ├── ARCHITECTURE.md           # System architecture, signal flow, and derivations
│   ├── SERIAL_PROTOCOL.md        # Detailed serial protocol & command reference
│   └── EXPERIMENTAL_PROTOCOL.md  # Physical laboratory validation procedures
└── platformio.ini                # PlatformIO build configuration for ESP32-S3
```
