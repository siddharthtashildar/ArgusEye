#include <Arduino.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>

// ── Pins ──────────────────────────────────────────────────────
#define TFT_CS   9
#define TFT_DC   15
#define TFT_RST  14
#define I2C_SDA  1
#define I2C_SCL  2
#define FPGA_TX  17 // ESP32 TX → FPGA RX

// ── Colors ────────────────────────────────────────────────────
#define COLOR_BG       0x0000
#define COLOR_SIGNAL   0x07E0
#define COLOR_ALERT    0xF800
#define COLOR_TEXT     0xFFFF
#define COLOR_HEADER   0x01AA
#define COLOR_GRID     0x1082
#define COLOR_DIM      0x3186
#define COLOR_PANEL    0x31A6
#define COLOR_BAR_BG   0x0842

// ── Display Zones ─────────────────────────────────────────────
#define PLOT_TOP    40
#define PLOT_BOT    210
#define PLOT_H      (PLOT_BOT - PLOT_TOP)
#define PLOT_LEFT   2
#define PLOT_RIGHT  238
#define PLOT_WIDTH  (PLOT_RIGHT - PLOT_LEFT)
#define PLOT_MID    (PLOT_TOP + (PLOT_H / 2))

#define HISTORY_TOP   218
#define HISTORY_H     42
#define HISTORY_POINTS 30

// ── DSP Tuning ────────────────────────────────────────────────
#define SAMPLE_RATE   400
#define BLOCK_SIZE    40
#define THRESHOLD     24000
#define MAX_VARIANCE  260000
#define HUM_SQUELCH   160

Adafruit_ST7789 tft = Adafruit_ST7789(TFT_CS, TFT_DC, TFT_RST);
Adafruit_ADS1115 ads;

int screenW = 240;
int screenH = 320;
int plotX = PLOT_LEFT;
int lastY = PLOT_MID;

float dynamicBaseline = 13200.0f;
bool baselineReady = false;
int baselineCount = 0;

float energySum = 0;
int sampleCount = 0;
uint8_t signalStrength = 0;
bool motionDetected = false;

uint16_t motionHistory[HISTORY_POINTS];
int historyIndex = 0;

bool fpgaLinked = false;
uint32_t lastLinkMs = 0;
uint32_t lastBlinkMs = 0;
bool blinkOn = false;

uint32_t lastSampleMs = 0;

static float clampf(float value, float minVal, float maxVal) {
    return (value < minVal) ? minVal : (value > maxVal ? maxVal : value);
}

static float mapFloat(float x, float inMin, float inMax, float outMin, float outMax) {
    if (inMax == inMin) return outMin;
    return (x - inMin) * (outMax - outMin) / (inMax - inMin) + outMin;
}

void drawGrid() {
    for (int x = PLOT_LEFT; x <= PLOT_RIGHT; x += 20) {
        tft.drawFastVLine(x, PLOT_TOP, PLOT_H, COLOR_DIM);
    }
    for (int y = PLOT_TOP; y <= PLOT_BOT; y += 25) {
        tft.drawFastHLine(PLOT_LEFT, y, PLOT_WIDTH, COLOR_DIM);
    }
    tft.drawFastHLine(PLOT_LEFT, PLOT_MID, PLOT_WIDTH, COLOR_GRID);
}

void drawStaticUI() {
    tft.fillScreen(COLOR_BG);

    tft.fillRect(0, 0, screenW, 32, COLOR_HEADER);
    tft.setTextColor(COLOR_TEXT);
    tft.setTextSize(2);
    tft.setCursor(10, 6);
    tft.print("ARGUSEYE");

    tft.drawRect(screenW - 92, 6, 86, 20, COLOR_TEXT);
    tft.setTextSize(1);
    tft.setCursor(screenW - 86, 11);
    tft.print("FPGA LINK");
    tft.fillCircle(screenW - 16, 16, 4, COLOR_DIM);

    tft.drawRect(6, 36, 116, 84, COLOR_PANEL);
    tft.drawRect(6, 126, 116, 74, COLOR_PANEL);
    tft.drawRect(126, 36, 108, 64, COLOR_PANEL);
    tft.drawRect(126, 104, 108, 96, COLOR_PANEL);

    tft.setTextSize(1);
    tft.setCursor(12, 42);
    tft.print("SIGNAL PATH");
    tft.setCursor(12, 58);
    tft.print("HB100 → LM358 → ADS1115");
    tft.setCursor(12, 76);
    tft.print("ESP32 DSP + FPGA VIEW");

    tft.setCursor(132, 42);
    tft.print("STATUS PANEL");
    tft.setCursor(132, 58);
    tft.print("Motion / Strength");

    tft.setCursor(12, 132);
    tft.print("GRAPH MODE");
    tft.setCursor(12, 150);
    tft.print("Live waveform + power");

    tft.setCursor(132, 110);
    tft.print("ALERT GAUGE");
    tft.setCursor(132, 130);
    tft.print("Signal meter + history");

    tft.drawRect(PLOT_LEFT - 1, PLOT_TOP - 1, PLOT_WIDTH + 2, PLOT_H + 2, COLOR_TEXT);
    drawGrid();
}

void drawCalibrationFrame(int percent) {
    tft.fillRect(0, PLOT_BOT + 2, screenW, screenH - PLOT_BOT - 2, COLOR_BG);
    tft.setTextColor(COLOR_TEXT);
    tft.setTextSize(2);
    tft.setCursor(10, PLOT_BOT + 10);
    tft.print("CALIBRATING...");

    int fillWidth = map(percent, 0, 100, 0, screenW - 24);
    tft.drawRect(10, PLOT_BOT + 40, screenW - 20, 16, COLOR_TEXT);
    tft.fillRect(12, PLOT_BOT + 42, fillWidth, 12, COLOR_SIGNAL);
}

void updateFPGAIndicator() {
    if (fpgaLinked && blinkOn) {
        tft.fillCircle(screenW - 16, 16, 4, COLOR_ALERT);
    } else if (fpgaLinked) {
        tft.fillCircle(screenW - 16, 16, 4, COLOR_SIGNAL);
    } else {
        tft.fillCircle(screenW - 16, 16, 4, COLOR_DIM);
    }
}

void updateStatusPanel(float variance) {
    tft.fillRect(130, 44, 106, 56, COLOR_BG);
    tft.fillRect(130, 112, 106, 70, COLOR_BG);

    tft.setTextColor(COLOR_TEXT);
    tft.setTextSize(1);
    tft.setCursor(132, 46);
    tft.print("MOTION:");
    tft.setCursor(132, 58);
    tft.setTextColor(motionDetected ? COLOR_ALERT : COLOR_GRID);
    tft.print(motionDetected ? "ACTIVE" : "IDLE  ");

    tft.setTextColor(COLOR_TEXT);
    tft.setCursor(132, 74);
    tft.print("STRENGTH:");
    tft.setCursor(132, 86);
    tft.print(signalStrength);

    tft.setCursor(132, 104);
    tft.print("BASELINE:");
    tft.setCursor(132, 116);
    tft.print((int)dynamicBaseline);

    tft.setCursor(132, 128);
    tft.print("ENERGY:");
    tft.setCursor(132, 140);
    tft.print((int)variance);

    if (motionDetected) {
        tft.fillRect(126, 157, map(signalStrength, 0, 255, 6, 100), 10, COLOR_ALERT);
        tft.drawRect(126, 157, 100, 10, COLOR_TEXT);
    } else {
        tft.drawRect(126, 157, 100, 10, COLOR_TEXT);
    }
}

void drawMotionHistory() {
    tft.fillRect(6, HISTORY_TOP, screenW - 12, HISTORY_H, COLOR_BG);
    tft.setTextColor(COLOR_TEXT);
    tft.setTextSize(1);
    tft.setCursor(10, HISTORY_TOP + 2);
    tft.print("MOTION HISTORY");

    int barWidth = (screenW - 32) / HISTORY_POINTS;
    for (int i = 0; i < HISTORY_POINTS; i++) {
        int index = (historyIndex + i) % HISTORY_POINTS;
        int x = 10 + i * barWidth;
        int h = motionHistory[index] ? 28 : 6;
        uint16_t color = motionHistory[index] ? COLOR_ALERT : COLOR_DIM;
        tft.fillRect(x, HISTORY_TOP + 16 + (28 - h), barWidth - 2, h, color);
    }
}

void sendToFPGA() {
    char status = motionDetected ? 'M' : 'C';
    Serial2.write(status);
    Serial2.write(signalStrength);
    Serial.printf("FPGA send: %c, %d\n", status, signalStrength);
    fpgaLinked = true;
    lastLinkMs = millis();
}

void resetPlotArea() {
    tft.fillRect(PLOT_LEFT, PLOT_TOP, PLOT_WIDTH, PLOT_H, COLOR_BG);
    drawGrid();
    plotX = PLOT_LEFT;
    lastY = PLOT_MID;
}

void setup() {
    delay(2000);
    Serial.begin(115200);
    Serial.println("ArgusEye booting...");
    Serial.printf("FPGA UART TX -> GPIO%d\n", FPGA_TX);
    Serial.printf("I2C bus configured: SDA=%d, SCL=%d\n", I2C_SDA, I2C_SCL);
    Serial.println("Initializing ADS1115...");

    Serial2.begin(9600, SERIAL_8N1, -1, FPGA_TX);
    Serial.println("FPGA UART ready.");

    Wire.begin(I2C_SDA, I2C_SCL);
    if (!ads.begin(0x48, &Wire)) {
        Serial.println("ERROR: ADS1115 not found! Check I2C wiring.");
        while (1);
    }
    Serial.println("ADS1115 detected.");
    ads.setGain(GAIN_SIXTEEN);

    tft.init(240, 320);
    tft.setRotation(1);
    Serial.println("TFT display initialized.");

    drawStaticUI();
    drawCalibrationFrame(0);
    tft.invertDisplay(false);
    Serial.println("Display UI ready. Beginning calibration...");
}

void loop() {
    uint32_t now = millis();
    if (now - lastSampleMs < (1000 / SAMPLE_RATE)) {
        if (now - lastBlinkMs > 500) {
            blinkOn = !blinkOn;
            lastBlinkMs = now;
            updateFPGAIndicator();
        }
        return;
    }

    lastSampleMs = now;
    int16_t rawValue = ads.readADC_SingleEnded(0);

    if (!baselineReady) {
        dynamicBaseline = (dynamicBaseline * baselineCount + rawValue) / (baselineCount + 1);
        baselineCount++;
        int progress = map(baselineCount, 0, 200, 0, 100);
        drawCalibrationFrame(progress);
        if (baselineCount % 50 == 0) {
            Serial.printf("Calibration progress: %d%%, baseline=%.1f\n", progress, dynamicBaseline);
        }
        if (baselineCount >= 200) {
            baselineReady = true;
            Serial.printf("Baseline calibration complete: %.1f\n", dynamicBaseline);
            tft.fillRect(0, PLOT_BOT + 2, screenW, screenH - PLOT_BOT - 2, COLOR_BG);
            tft.setTextColor(COLOR_TEXT);
            tft.setCursor(10, PLOT_BOT + 10);
            tft.setTextSize(2);
            tft.print("READY");
            delay(200);
            resetPlotArea();
            drawMotionHistory();
        }
        return;
    }

    dynamicBaseline = dynamicBaseline * 0.996f + rawValue * 0.004f;
    float sample = rawValue - dynamicBaseline;
    if (abs(sample) < HUM_SQUELCH) sample = 0;
    energySum += sample * sample;
    sampleCount++;

    int yPos = map(sample, -4200, 4200, PLOT_BOT, PLOT_TOP);
    yPos = constrain(yPos, PLOT_TOP + 1, PLOT_BOT - 1);

    tft.fillRect(plotX, PLOT_TOP, 2, PLOT_H, COLOR_BG);
    if ((plotX - PLOT_LEFT) % 20 == 0) {
        tft.drawFastVLine(plotX, PLOT_TOP, PLOT_H, COLOR_DIM);
    }
    if (plotX == PLOT_LEFT) {
        tft.drawPixel(plotX, yPos, motionDetected ? COLOR_ALERT : COLOR_SIGNAL);
    } else {
        tft.drawLine(plotX - 1, lastY, plotX, yPos, motionDetected ? COLOR_ALERT : COLOR_SIGNAL);
    }
    lastY = yPos;
    plotX += 2;
    if (plotX >= PLOT_RIGHT) {
        resetPlotArea();
    }

    if (sampleCount >= BLOCK_SIZE) {
        float variance = energySum / (float)sampleCount;
        motionDetected = (variance > THRESHOLD);
        signalStrength = motionDetected ? (uint8_t)clampf(mapFloat(variance, THRESHOLD, MAX_VARIANCE, 48, 255), 0, 255) : 0;
        if (!motionDetected) signalStrength = 0;

        Serial.printf("DATA BLOCK: raw=%.0f baseline=%.1f variance=%.0f motion=%s strength=%d\n",
            (float)rawValue, dynamicBaseline, variance,
            motionDetected ? "YES" : "NO ", signalStrength);

        energySum = 0;
        sampleCount = 0;

        motionHistory[historyIndex] = motionDetected ? 1 : 0;
        historyIndex = (historyIndex + 1) % HISTORY_POINTS;
        drawMotionHistory();
        updateStatusPanel(variance);
        sendToFPGA();
    }

    if (now - lastLinkMs > 1600) {
        fpgaLinked = false;
    }
    if (now - lastBlinkMs > 500) {
        blinkOn = !blinkOn;
        lastBlinkMs = now;
        updateFPGAIndicator();
    }
}
