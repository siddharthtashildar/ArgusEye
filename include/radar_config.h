#pragma once
#include <Arduino.h>

// ==============================================================================
// ARGUS-EYE HARDWARE & FIRMWARE CONFIGURATION
// ==============================================================================

// Hardware Pin Assignments (Preserved from existing setup)
#define PIN_I2C_SDA     21
#define PIN_I2C_SCL     18
#define PIN_TFT_CS      9
#define PIN_TFT_DC      15
#define PIN_TFT_RST     14
#define PIN_TFT_MOSI    11
#define PIN_TFT_SCLK    12
#define PIN_FPGA_TX     17

// Serial Communication Speeds
#define SERIAL_PC_BAUD      115200
#define SERIAL_FPGA_BAUD    9600

// ADS1115 Sampling Cadence
// ADS1115 supports: 128, 250, 475, 860 SPS.
// Target 200 Hz pacing (5000 µs). At 475 or 860 SPS, conversion takes 1.16 - 2.1 ms,
// leaving ample margin for stable, non-blocking I2C reads without jitter.
#define DEFAULT_TARGET_SAMPLE_INTERVAL_US  5000  // 200 Hz nominal sampling
#define ADS_I2C_CLOCK_HZ                   400000 // Fast-mode I2C (400 kHz)

// UI and Telemetry Throttling Intervals (ms)
#define INTERVAL_TFT_UPDATE_MS    40   // 25 Hz TFT visual update rate
#define INTERVAL_FPGA_SEND_MS     100  // 10 Hz FPGA status forwarding
#define INTERVAL_METRICS_REPORT_MS 1000 // 1 Hz diagnostic report on sample rate & health

// Default Algorithm Parameters
#define DEFAULT_DETECTOR_MODE     1    // 0 = Legacy Baseline/Deadband, 1 = Adaptive Causal
#define DEFAULT_TRIGGER_THRESHOLD 120  // ADC counts above noise floor to trigger
#define DEFAULT_RELEASE_RATIO     0.65 // Release threshold = Trigger * 0.65
#define DEFAULT_CONFIRM_SAMPLES   3    // Samples above trigger before asserting motion (~15ms)
#define DEFAULT_HOLD_SAMPLES      30   // Cooldown hold samples (~150ms) to merge zero-crossings
#define DEFAULT_DEADBAND          50   // Legacy deadband threshold
