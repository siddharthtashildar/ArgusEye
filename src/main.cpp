#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>

#include "radar_config.h"
#include "radar_dsp.h"
#include "serial_protocol.h"

// ==============================================================================
// ARGUS-EYE EMBEDDED MOTION DETECTION SYSTEM (ESP32-S3)
// ==============================================================================

// Hardware Objects
Adafruit_ADS1115 ads;
Adafruit_ST7789  tft = Adafruit_ST7789(&SPI, PIN_TFT_CS, PIN_TFT_DC, PIN_TFT_RST);
RadarDSP         radarDsp;

// Hardware & Display State
int      screenW = 320;
int      screenH = 240;
int      xPos = 0;
int      lastY = 120;
bool     adsOK = false;

// Timing & Cadence Tracking
uint32_t targetIntervalUs = DEFAULT_TARGET_SAMPLE_INTERVAL_US; // 5000 us = 200 Hz
uint32_t lastSampleUs = 0;
uint32_t lastTFTUpdateMs = 0;
uint32_t lastFPGASendMs = 0;
uint32_t lastDiagnosticsMs = 0;
uint32_t motionStartMs = 0;

// Diagnostics & Sample Rate Estimation
uint32_t samplesInWindow = 0;
uint32_t windowStartUs = 0;
float    effectiveSampleRate = 0.0f;
uint32_t timingAnomaliesCount = 0;

// Latest Telemetry Cache
DSPTelemetry latestTelem;
bool     hasSample = false;
bool     wasMotion = false;

// Serial Command Line Buffer
char cmdBuffer[64];
uint8_t cmdIdx = 0;

// Serial Output Line Buffer (pre-allocated to avoid heap churn)
char serialTxBuffer[256];

// Static UI Drawing (Preserved from existing UI layout)
void drawStaticUI() {
    tft.fillScreen(0x0000); // C_BG

    // Header bar
    tft.fillRect(0, 0, screenW, 24, 0x0200); // C_DKGREEN
    tft.setTextColor(0x07E0); // C_GREEN
    tft.setTextSize(2);
    tft.setCursor(4, 4);
    tft.print("ARGUSEYE");
    tft.setTextSize(1);
    tft.setTextColor(0x02A0); // C_DIMG
    tft.setCursor(112, 8);
    tft.print("HB100 MICROWAVE RADAR");

    // Horizontal center dotted grid
    int mid = 24 + (screenH - 80) / 2;
    for (int x = 0; x < screenW; x += 5)
        tft.drawPixel(x, mid, 0x0140);

    // Vertical grid lines
    for (int x = 40; x < screenW; x += 40)
        for (int y = 25; y < screenH - 56; y += 3)
            tft.drawPixel(x, y, 0x0140);

    // Quarter lines
    int q = (screenH - 80) / 4;
    for (int x = 0; x < screenW; x += 5) {
        tft.drawPixel(x, 25 + q,   0x0140);
        tft.drawPixel(x, 25 + 3*q, 0x0140);
    }

    // Info strip border
    tft.drawFastHLine(0, screenH - 55, screenW, 0x02A0);
    tft.drawFastVLine(79,  screenH - 54, 54, 0x02A0);
    tft.drawFastVLine(159, screenH - 54, 54, 0x02A0);
    tft.drawFastVLine(239, screenH - 54, 54, 0x02A0);

    // Info strip labels
    tft.setTextSize(1);
    tft.setTextColor(0x0140);
    tft.setCursor(4,   screenH - 52); tft.print("SIGNAL");
    tft.setCursor(84,  screenH - 52); tft.print("STATUS");
    tft.setCursor(164, screenH - 52); tft.print("PEAK");
    tft.setCursor(244, screenH - 52); tft.print("EVENTS");
}

void updateInfoStrip(int16_t signal, int16_t envelope, bool motion, uint32_t eventCount, int16_t peak) {
    int sy = screenH - 40;

    // Box 1: Signal strength bar
    tft.fillRect(1, screenH - 42, 78, 40, 0x0000);
    int bars = map(abs(signal), 0, 500, 0, 9);
    bars = constrain(bars, 0, 9);
    for (int i = 0; i < 9; i++) {
        uint16_t c = 0x0140;
        if (i < bars)
            c = (bars > 6) ? 0xF800 : (bars > 3) ? 0xFFE0 : 0x07E0;
        tft.fillRect(3 + i * 8, sy, 6, 14, c);
    }
    tft.setTextSize(1);
    tft.setTextColor(0x02A0);
    tft.setCursor(4, sy + 18);
    tft.printf("ENV:%4d", envelope);

    // Box 2: Status
    tft.fillRect(81, screenH - 42, 77, 40, 0x0000);
    if (motion) {
        tft.setTextColor(0xF800);
        tft.setTextSize(2);
        tft.setCursor(85, sy - 4);
        tft.print("MOTION");
        tft.setTextSize(1);
        tft.setTextColor(0xF800);
        tft.setCursor(84, sy + 18);
        uint32_t dur = (millis() - motionStartMs) / 1000;
        tft.printf("T+%02lus", (unsigned long)dur);
    } else {
        tft.setTextColor(0x07E0);
        tft.setTextSize(1);
        tft.setCursor(84, sy - 2);
        tft.print("SCANNING");
        static int dotCnt = 0;
        dotCnt = (dotCnt + 1) % 4;
        tft.setCursor(84, sy + 10);
        for (int d = 0; d < dotCnt; d++) tft.print(".");
    }

    // Box 3: Peak signal
    tft.fillRect(161, screenH - 42, 77, 40, 0x0000);
    tft.setTextColor(0x07FF);
    tft.setTextSize(2);
    tft.setCursor(164, sy - 4);
    tft.printf("%4d", peak);
    tft.setTextSize(1);
    tft.setTextColor(0x0140);
    tft.setCursor(164, sy + 18);
    tft.print("MAX SIG");

    // Box 4: Events
    tft.fillRect(241, screenH - 42, 78, 40, 0x0000);
    tft.setTextColor(eventCount > 0 ? 0xFFE0 : 0x0140);
    tft.setTextSize(3);
    tft.setCursor(248, sy - 6);
    tft.printf("%03lu", (unsigned long)(eventCount % 1000));
    tft.setTextSize(1);
    tft.setTextColor(0x0140);
    tft.setCursor(244, sy + 18);
    tft.print("DETECTED");
}

void processSerialCommands() {
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\r' || c == '\n') {
            if (cmdIdx > 0) {
                cmdBuffer[cmdIdx] = '\0';
                SerialCommand cmd = SerialProtocol::parseCommandLine(cmdBuffer);
                switch (cmd.type) {
                    case CMD_SET_THRESHOLD:
                        radarDsp.setTriggerThreshold((int16_t)cmd.intParam);
                        Serial.printf("[ACK] Threshold set to %d ADC\n", (int)cmd.intParam);
                        break;
                    case CMD_SET_DETECTOR:
                        radarDsp.setDetectorMode((uint8_t)cmd.intParam);
                        Serial.printf("[ACK] Detector mode set to %s\n", (cmd.intParam == 1) ? "ADAPTIVE" : "LEGACY");
                        break;
                    case CMD_CALIBRATE:
                        radarDsp.startCalibration(2000);
                        Serial.println("[ACK] Calibration started (2000ms quiet calibration)");
                        break;
                    case CMD_RESET:
                        radarDsp.reset();
                        timingAnomaliesCount = 0;
                        Serial.println("[ACK] Radar DSP and event counters reset");
                        break;
                    case CMD_GET_STATUS: {
                        char statusBuf[160];
                        SerialProtocol::formatStatusReport(radarDsp, effectiveSampleRate, timingAnomaliesCount, statusBuf, sizeof(statusBuf));
                        Serial.println(statusBuf);
                        break;
                    }
                    case CMD_PING:
                        Serial.println("PONG");
                        break;
                    default:
                        break;
                }
                cmdIdx = 0;
            }
        } else if (cmdIdx < sizeof(cmdBuffer) - 1) {
            cmdBuffer[cmdIdx++] = c;
        }
    }
}

void setup() {
    delay(1000);
    Serial.begin(SERIAL_PC_BAUD);
    Serial.println("=== BOOT OK: ARGUS-EYE RADAR SYSTEM ===");

    // Initialize FPGA UART transmission link
    Serial2.begin(SERIAL_FPGA_BAUD, SERIAL_8N1, -1, PIN_FPGA_TX);

    // Initialize I2C with Fast Mode (400 kHz)
    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
    Wire.setClock(ADS_I2C_CLOCK_HZ);
    Serial.println("I2C started at 400kHz");

    // Initialize ADS1115 external ADC
    if (!ads.begin(0x48, &Wire)) {
        Serial.println("ERROR: ADS1115 not found at 0x48!");
        adsOK = false;
    } else {
        Serial.println("ADS1115 OK");
        ads.setGain(GAIN_ONE);               // +/- 4.096V 1 bit = 0.125mV
        ads.setDataRate(RATE_ADS1115_860SPS);// Fast conversion (~1.16ms)
        adsOK = true;
    }

    // Initialize ST7789 TFT Display via Hardware SPI
    SPI.begin(PIN_TFT_SCLK, -1, PIN_TFT_MOSI, PIN_TFT_CS);
    tft.init(240, 320);
    tft.setRotation(1);
    screenW = tft.width();
    screenH = tft.height();
    lastY = (screenH - 56) / 2 + 25;

    drawStaticUI();
    tft.invertDisplay(false);

    if (!adsOK) {
        tft.setCursor(10, 50);
        tft.setTextColor(0xF800);
        tft.setTextSize(2);
        tft.print("ADS1115 NOT FOUND");
        tft.setCursor(10, 80);
        tft.print("Check wiring!");
    }

    lastSampleUs = micros();
    windowStartUs = micros();
    samplesInWindow = 0;

    Serial.println("Setup done. Telemetry streaming active.");
}

void loop() {
    if (!adsOK) {
        Serial.println("ADS1115 missing");
        delay(2000);
        return;
    }

    // Process any serial configuration commands sent from PC
    processSerialCommands();

    // ── HIGH-PRIORITY PACED ACQUISITION & DSP PIPELINE ───────────────────────
    uint32_t nowUs = micros();
    uint32_t elapsedUs = nowUs - lastSampleUs;

    // Check if it's time for the next sample (paced acquisition)
    if (elapsedUs >= targetIntervalUs) {
        lastSampleUs = nowUs;
        samplesInWindow++;

        // Read ADS1115 single-ended channel 0
        int16_t rawVal = ads.readADC_SingleEnded(0);

        // Process through embedded DSP pipeline (Causal filter, envelope, adaptive threshold)
        latestTelem = radarDsp.processSample(rawVal, nowUs, elapsedUs);
        hasSample = true;

        if (latestTelem.timingAnomaly) {
            timingAnomaliesCount++;
        }

        // Format and stream serial telemetry line (backward compatible with original regex)
        SerialProtocol::formatTelemetry(latestTelem, serialTxBuffer, sizeof(serialTxBuffer));
        Serial.println(serialTxBuffer);

        // Track motion start for TFT duration display
        if (latestTelem.selectedMotion && !wasMotion) {
            motionStartMs = millis();
        }
        wasMotion = latestTelem.selectedMotion;
    }

    // ── DIAGNOSTIC SAMPLE RATE ESTIMATION (1 Hz) ─────────────────────────────
    uint32_t nowMs = millis();
    if (nowMs - lastDiagnosticsMs >= INTERVAL_METRICS_REPORT_MS) {
        lastDiagnosticsMs = nowMs;
        uint32_t dtWindowUs = micros() - windowStartUs;
        if (dtWindowUs > 0) {
            effectiveSampleRate = (float)samplesInWindow * 1000000.0f / (float)dtWindowUs;
        }
        samplesInWindow = 0;
        windowStartUs = micros();
    }

    // ── THROTTLED TFT VISUAL UPDATE (25 Hz) ──────────────────────────────────
    // Decoupled from ADC sampling so SPI operations never block sample timing
    if (hasSample && (nowMs - lastTFTUpdateMs >= INTERVAL_TFT_UPDATE_MS)) {
        lastTFTUpdateMs = nowMs;

        int yPos = map(latestTelem.acSignal, -500, 500, screenH - 56, 25);
        yPos = constrain(yPos, 26, screenH - 57);

        // Clear scan column ahead of draw
        tft.drawFastVLine(xPos + 2, 25, screenH - 81, 0x0000);
        tft.drawFastVLine(xPos + 3, 25, screenH - 81, 0x0000);
        if ((xPos + 2) % 40 == 0) {
            for (int y = 25; y < screenH - 56; y += 3)
                tft.drawPixel(xPos + 2, y, 0x0140);
        }

        uint16_t drawColor = latestTelem.selectedMotion ? 0xF800 : 0x07E0;
        tft.drawLine(xPos - 1, lastY, xPos, yPos, drawColor);

        // Sweep indicator cursor
        tft.drawFastVLine((xPos + 4) % screenW, 25, screenH - 81, 0x0000);
        tft.drawFastVLine((xPos + 5) % screenW, 25, screenH - 81,
            latestTelem.selectedMotion ? 0x3800 : 0x0060);

        lastY = yPos;
        xPos++;
        if (xPos >= screenW) xPos = 0;

        // Update info strip readouts
        updateInfoStrip(
            latestTelem.acSignal,
            latestTelem.envelope,
            latestTelem.selectedMotion,
            radarDsp.getEventCount(),
            radarDsp.getPeakSignal()
        );
    }

    // ── FPGA UART TRANSMISSION (10 Hz) ───────────────────────────────────────
    if (nowMs - lastFPGASendMs >= INTERVAL_FPGA_SEND_MS) {
        lastFPGASendMs = nowMs;
        if (hasSample) {
            Serial2.write(latestTelem.selectedMotion ? 'M' : 'C');
            uint8_t str = (uint8_t)constrain(
                map(latestTelem.envelope, 0, 500, 0, 255), 0, 255);
            Serial2.write(str);
        }
    }
}