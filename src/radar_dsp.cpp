#include "radar_dsp.h"
#include <math.h>

RadarDSP::RadarDSP()
    : m_detectorMode(DEFAULT_DETECTOR_MODE)
    , m_triggerThreshold(DEFAULT_TRIGGER_THRESHOLD)
    , m_releaseThreshold((int16_t)(DEFAULT_TRIGGER_THRESHOLD * DEFAULT_RELEASE_RATIO))
    , m_legacyDeadband(DEFAULT_DEADBAND)
    , m_confirmSamples(DEFAULT_CONFIRM_SAMPLES)
    , m_holdSamples(DEFAULT_HOLD_SAMPLES)
    , m_dynamicBaseline(0.0f)
    , m_baselineInitialized(false)
    , m_hpfXPrev(0.0f)
    , m_hpfYPrev(0.0f)
    , m_lpfYPrev(0.0f)
    , m_envelope(0.0f)
    , m_noiseFloor(15.0f)
    , m_aboveCounter(0)
    , m_holdCounter(0)
    , m_adaptiveActive(false)
    , m_legacyActive(false)
    , m_sampleIndex(0)
    , m_eventCount(0)
    , m_peakSignal(0)
    , m_prevSelectedMotion(false)
    , m_calibrating(false)
    , m_calibStartMs(0)
    , m_calibDurationMs(2000)
    , m_calibSampleCount(0)
    , m_calibSum(0.0f)
    , m_calibEnvSum(0.0f)
{
}

void RadarDSP::reset() {
    m_baselineInitialized = false;
    m_dynamicBaseline = 0.0f;
    m_hpfXPrev = 0.0f;
    m_hpfYPrev = 0.0f;
    m_lpfYPrev = 0.0f;
    m_envelope = 0.0f;
    m_noiseFloor = 15.0f;
    m_aboveCounter = 0;
    m_holdCounter = 0;
    m_adaptiveActive = false;
    m_legacyActive = false;
    m_eventCount = 0;
    m_peakSignal = 0;
    m_prevSelectedMotion = false;
    m_calibrating = false;
}

void RadarDSP::setDetectorMode(uint8_t mode) {
    m_detectorMode = (mode > 0) ? 1 : 0;
    m_aboveCounter = 0;
    m_holdCounter = 0;
}

void RadarDSP::setTriggerThreshold(int16_t thresh) {
    if (thresh < 10) thresh = 10;
    if (thresh > 5000) thresh = 5000;
    m_triggerThreshold = thresh;
    m_releaseThreshold = (int16_t)(thresh * DEFAULT_RELEASE_RATIO);
}

void RadarDSP::setLegacyDeadband(int16_t deadband) {
    if (deadband < 0) deadband = 0;
    m_legacyDeadband = deadband;
}

void RadarDSP::setConfirmationSamples(uint8_t count) {
    if (count < 1) count = 1;
    m_confirmSamples = count;
}

void RadarDSP::setHoldSamples(uint16_t count) {
    m_holdSamples = count;
}

void RadarDSP::startCalibration(uint32_t durationMs) {
    m_calibrating = true;
    m_calibStartMs = millis();
    m_calibDurationMs = durationMs;
    m_calibSampleCount = 0;
    m_calibSum = 0.0f;
    m_calibEnvSum = 0.0f;
}

DSPTelemetry RadarDSP::processSample(int16_t rawAdc, uint32_t timestampUs, uint32_t deltaUs) {
    m_sampleIndex++;

    // Timing anomaly detection: nominal is DEFAULT_TARGET_SAMPLE_INTERVAL_US (5000 us).
    // Anomaly if delta > 1.5x nominal or < 0.5x nominal.
    bool timingAnomaly = (deltaUs > (DEFAULT_TARGET_SAMPLE_INTERVAL_US * 3 / 2)) ||
                         (deltaUs < (DEFAULT_TARGET_SAMPLE_INTERVAL_US / 2));

    // 1. Dynamic Baseline Tracking (Exponential Moving Average)
    if (!m_baselineInitialized) {
        m_dynamicBaseline = (float)rawAdc;
        m_baselineInitialized = true;
        m_hpfXPrev = (float)rawAdc;
    } else {
        // Slow baseline adaptation (alpha = 0.01) matches original firmware behavior
        m_dynamicBaseline = (m_dynamicBaseline * 0.99f) + ((float)rawAdc * 0.01f);
    }
    int16_t baselineInt = (int16_t)roundf(m_dynamicBaseline);
    int16_t acSignal = rawAdc - baselineInt;

    // 2. Legacy Detector (Reference baseline/deadband detector)
    int16_t legacySig = acSignal;
    if (abs(legacySig) < m_legacyDeadband) {
        legacySig = 0;
    }
    m_legacyActive = (abs(legacySig) > m_triggerThreshold);

    // 3. Digital Bandpass Filter (Causal HPF + LPF tuned for 5 - 80 Hz at 200 Hz)
    // High-pass filter: alphaHP = 0.888f
    const float alphaHP = 0.888f;
    float rawF = (float)rawAdc;
    float hpfY = alphaHP * (m_hpfYPrev + rawF - m_hpfXPrev);
    m_hpfXPrev = rawF;
    m_hpfYPrev = hpfY;

    // Low-pass filter: betaLP = 0.715f
    const float betaLP = 0.715f;
    float lpfY = m_lpfYPrev + betaLP * (hpfY - m_lpfYPrev);
    m_lpfYPrev = lpfY;
    int16_t filteredSignal = (int16_t)roundf(lpfY);

    // 4. Envelope Follower (Causal rectified leaky peak tracker)
    float mag = fabsf(lpfY);
    if (mag > m_envelope) {
        // Fast attack (alpha = 0.35)
        m_envelope = 0.35f * mag + 0.65f * m_envelope;
    } else {
        // Slower decay (alpha = 0.05) to bridge Doppler wave zero-crossings
        m_envelope = 0.05f * mag + 0.95f * m_envelope;
    }
    int16_t envelopeInt = (int16_t)roundf(m_envelope);

    // 5. Online Calibration / Quiet Noise Tracking
    if (m_calibrating) {
        m_calibSampleCount++;
        m_calibSum += rawF;
        m_calibEnvSum += m_envelope;
        if (millis() - m_calibStartMs >= m_calibDurationMs) {
            m_calibrating = false;
            if (m_calibSampleCount > 10) {
                m_dynamicBaseline = m_calibSum / (float)m_calibSampleCount;
                float quietNoise = m_calibEnvSum / (float)m_calibSampleCount;
                m_noiseFloor = fmaxf(5.0f, quietNoise);
                // Adjust trigger threshold to quiet noise * 2.5
                int16_t autoThresh = (int16_t)roundf(m_noiseFloor * 2.5f + 15.0f);
                if (autoThresh < 30) autoThresh = 30;
                setTriggerThreshold(autoThresh);
            }
        }
    } else {
        // When not in motion and hold is exhausted, track background noise
        if (!m_adaptiveActive && m_holdCounter == 0) {
            m_noiseFloor = 0.998f * m_noiseFloor + 0.002f * m_envelope;
            if (m_noiseFloor < 3.0f) m_noiseFloor = 3.0f;
        }
    }

    // 6. Adaptive Noise-Aware Threshold Calculation
    int16_t dynamicTrigger = m_triggerThreshold;
    int16_t noiseMargin = (int16_t)roundf(m_noiseFloor * 2.0f);
    if (dynamicTrigger < noiseMargin) {
        dynamicTrigger = noiseMargin;
    }
    int16_t dynamicRelease = (int16_t)roundf((float)dynamicTrigger * DEFAULT_RELEASE_RATIO);
    if (dynamicRelease < (int16_t)roundf(m_noiseFloor)) {
        dynamicRelease = (int16_t)roundf(m_noiseFloor);
    }

    // 7. Causal Hysteresis & Confirmation Logic
    if (!m_adaptiveActive) {
        if (m_envelope >= (float)dynamicTrigger) {
            m_aboveCounter++;
            if (m_aboveCounter >= m_confirmSamples) {
                m_adaptiveActive = true;
                m_holdCounter = m_holdSamples;
                m_aboveCounter = 0;
            }
        } else {
            m_aboveCounter = 0;
        }
    } else {
        // Currently in motion: check release threshold and hold window
        if (m_envelope >= (float)dynamicRelease) {
            // Signal remains active, refresh hold-off timer
            m_holdCounter = m_holdSamples;
        } else {
            if (m_holdCounter > 0) {
                m_holdCounter--;
            } else {
                m_adaptiveActive = false;
                m_aboveCounter = 0;
            }
        }
    }

    // 8. Select Active Detector
    bool selectedMotion = (m_detectorMode == 1) ? m_adaptiveActive : m_legacyActive;

    // Track peak signal magnitude
    int16_t absSig = abs(acSignal);
    if (absSig > m_peakSignal) {
        m_peakSignal = absSig;
    }

    // Event counter: trigger on rising edge
    if (selectedMotion && !m_prevSelectedMotion) {
        m_eventCount++;
    }
    m_prevSelectedMotion = selectedMotion;

    // Populate telemetry struct
    DSPTelemetry telem;
    telem.sampleIndex       = m_sampleIndex;
    telem.timestampUs       = timestampUs;
    telem.deltaUs           = deltaUs;
    telem.rawAdc            = rawAdc;
    telem.baselineAdc       = baselineInt;
    telem.acSignal          = acSignal;
    telem.filteredSignal    = filteredSignal;
    telem.envelope          = envelopeInt;
    telem.noiseFloor        = (int16_t)roundf(m_noiseFloor);
    telem.triggerThreshold  = dynamicTrigger;
    telem.releaseThreshold  = dynamicRelease;
    telem.legacyMotion      = m_legacyActive;
    telem.adaptiveMotion    = m_adaptiveActive;
    telem.selectedMotion    = selectedMotion;
    telem.detectorMode      = m_detectorMode;
    telem.timingAnomaly     = timingAnomaly;

    return telem;
}
