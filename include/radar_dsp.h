#pragma once
#include <Arduino.h>
#include "radar_config.h"

// ==============================================================================
// ARGUS-EYE EMBEDDED DSP PIPELINE FOR ESP32-S3
// ==============================================================================

struct DSPTelemetry {
    uint32_t sampleIndex;
    uint32_t timestampUs;
    uint32_t deltaUs;
    int16_t  rawAdc;
    int16_t  baselineAdc;
    int16_t  acSignal;        // Raw - Baseline
    int16_t  filteredSignal;  // Band-passed AC signal
    int16_t  envelope;        // Leaky rectified envelope
    int16_t  noiseFloor;      // Estimated quiet background noise
    int16_t  triggerThreshold;// Active threshold in ADC counts
    int16_t  releaseThreshold;// Hysteresis release threshold
    bool     legacyMotion;    // Legacy baseline/deadband detector result
    bool     adaptiveMotion;  // Causal adaptive detector result
    bool     selectedMotion;  // Motion output based on active detector mode
    uint8_t  detectorMode;    // 0 = Legacy, 1 = Adaptive
    bool     timingAnomaly;   // True if deltaUs deviated significantly from target
};

class RadarDSP {
public:
    RadarDSP();

    // Reset internal state, baseline, and filters
    void reset();

    // Configure algorithm parameters
    void setDetectorMode(uint8_t mode);
    void setTriggerThreshold(int16_t thresh);
    void setLegacyDeadband(int16_t deadband);
    void setConfirmationSamples(uint8_t count);
    void setHoldSamples(uint16_t count);

    // Calibration: initialize baseline and noise estimate from known quiet samples
    void startCalibration(uint32_t durationMs = 2000);
    bool isCalibrating() const { return m_calibrating; }

    // Primary sample processing function (causal, deterministic, zero heap allocation)
    DSPTelemetry processSample(int16_t rawAdc, uint32_t timestampUs, uint32_t deltaUs);

    // Diagnostic accessors
    uint32_t getEventCount() const { return m_eventCount; }
    int16_t  getPeakSignal() const { return m_peakSignal; }
    void     resetPeakSignal() { m_peakSignal = 0; }
    uint8_t  getDetectorMode() const { return m_detectorMode; }
    int16_t  getTriggerThreshold() const { return m_triggerThreshold; }
    int16_t  getReleaseThreshold() const { return m_releaseThreshold; }
    int16_t  getEstimatedNoiseFloor() const { return (int16_t)m_noiseFloor; }
    float    getBaseline() const { return m_dynamicBaseline; }

private:
    // Configuration state
    uint8_t  m_detectorMode;
    int16_t  m_triggerThreshold;
    int16_t  m_releaseThreshold;
    int16_t  m_legacyDeadband;
    uint8_t  m_confirmSamples;
    uint16_t m_holdSamples;

    // Baseline tracking
    float    m_dynamicBaseline;
    bool     m_baselineInitialized;

    // Bandpass filter state (cascaded 1st-order DC-block HPF + 1st-order anti-alias LPF)
    // Tuned for ~5 Hz to ~80 Hz passband at ~200 Hz sample rate
    float    m_hpfXPrev;
    float    m_hpfYPrev;
    float    m_lpfYPrev;

    // Envelope follower state
    float    m_envelope;

    // Noise floor tracker
    float    m_noiseFloor;

    // Adaptive hysteresis detector state
    uint8_t  m_aboveCounter;
    uint16_t m_holdCounter;
    bool     m_adaptiveActive;

    // Legacy detector state
    bool     m_legacyActive;

    // Event counter and statistics
    uint32_t m_sampleIndex;
    uint32_t m_eventCount;
    int16_t  m_peakSignal;
    bool     m_prevSelectedMotion;

    // Calibration state
    bool     m_calibrating;
    uint32_t m_calibStartMs;
    uint32_t m_calibDurationMs;
    uint32_t m_calibSampleCount;
    float    m_calibSum;
    float    m_calibEnvSum;
};
