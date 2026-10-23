#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>

// ── Pins ──────────────────────────────────────────────────────
#define I2C_SDA 21
#define I2C_SCL 18
#define TFT_CS    9
#define TFT_DC    15
#define TFT_RST   14
#define TFT_MOSI  11
#define TFT_SCLK  12
#define FPGA_TX 17   // add this wire tomorrow: ESP32 GPIO17 → FPGA JB pin2

// ── Tuning — NOT CHANGED ──────────────────────────────────────
int threshold       = 30;
const bool DEBUG_MODE = true;

// ── Colors ────────────────────────────────────────────────────
#define C_BG      0x0000
#define C_GREEN   0x07E0
#define C_RED     0xF800
#define C_WHITE   0xFFFF
#define C_CYAN    0x07FF
#define C_YELLOW  0xFFE0
#define C_DKGREEN 0x0200
#define C_DIMG    0x02A0
#define C_GRID    0x0140

// ── Objects ───────────────────────────────────────────────────
Adafruit_ADS1115 ads;
Adafruit_ST7789  tft = Adafruit_ST7789(TFT_CS, TFT_DC, TFT_MOSI, TFT_SCLK, TFT_RST);

// ── Globals ───────────────────────────────────────────────────
int     screenW, screenH;
int     xPos           = 0;
int     lastY          = 120;
float   dynamicBaseline = 0.0;
bool    adsOK          = false;

// ── New UI state ──────────────────────────────────────────────
int     eventCount     = 0;
int     lastSignal     = 0;
int     peakSignal     = 0;
uint32_t lastInfoDraw  = 0;
uint32_t lastFPGASend  = 0;
uint32_t motionStart   = 0;
bool    wasMotion      = false;
int     signalHistory[20];
int     histIdx        = 0;

// ─────────────────────────────────────────────────────────────
void drawStaticUI() {
    tft.fillScreen(C_BG);

    // ── Header ───────────────────────────────────────────────
    tft.fillRect(0, 0, screenW, 24, C_DKGREEN);
    tft.setTextColor(C_GREEN);
    tft.setTextSize(2);
    tft.setCursor(4, 4);
    tft.print("ARGUSEYE");
    tft.setTextSize(1);
    tft.setTextColor(C_DIMG);
    tft.setCursor(112, 8);
    tft.print("HB100 MICROWAVE RADAR");

    // ── Wave area grid ───────────────────────────────────────
    // horizontal center line dotted
    int mid = 24 + (screenH - 80) / 2;
    for (int x = 0; x < screenW; x += 5)
        tft.drawPixel(x, mid, C_GRID);

    // vertical grid lines
    for (int x = 40; x < screenW; x += 40)
        for (int y = 25; y < screenH - 56; y += 3)
            tft.drawPixel(x, y, C_GRID);

    // horizontal quarter lines
    int q = (screenH - 80) / 4;
    for (int x = 0; x < screenW; x += 5) {
        tft.drawPixel(x, 25 + q,     C_GRID);
        tft.drawPixel(x, 25 + 3*q,   C_GRID);
    }

    // ── Info strip border ────────────────────────────────────
    tft.drawFastHLine(0, screenH - 55, screenW, C_DIMG);
    tft.drawFastVLine(79,  screenH - 54, 54, C_DIMG);
    tft.drawFastVLine(159, screenH - 54, 54, C_DIMG);
    tft.drawFastVLine(239, screenH - 54, 54, C_DIMG);

    // ── Info strip labels ────────────────────────────────────
    tft.setTextSize(1);
    tft.setTextColor(C_GRID);
    tft.setCursor(4,   screenH - 52); tft.print("SIGNAL");
    tft.setCursor(84,  screenH - 52); tft.print("STATUS");
    tft.setCursor(164, screenH - 52); tft.print("PEAK");
    tft.setCursor(244, screenH - 52); tft.print("EVENTS");
}

// ─────────────────────────────────────────────────────────────
void updateInfoStrip(int signal, bool motion) {
    int sy = screenH - 40;   // value row y

    // ── Box 1: Signal strength bar ───────────────────────────
    tft.fillRect(1, screenH - 42, 78, 40, C_BG);
    int bars = map(abs(signal), 0, 500, 0, 9);
    bars = constrain(bars, 0, 9);
    for (int i = 0; i < 9; i++) {
        uint16_t c = C_GRID;
        if (i < bars)
            c = (bars > 6) ? C_RED : (bars > 3) ? C_YELLOW : C_GREEN;
        tft.fillRect(3 + i * 8, sy, 6, 14, c);
    }
    tft.setTextSize(1);
    tft.setTextColor(C_DIMG);
    tft.setCursor(4, sy + 18);
    tft.printf("RAW:%5d", abs(signal));

    // ── Box 2: Status ────────────────────────────────────────
    tft.fillRect(81, screenH - 42, 77, 40, C_BG);
    if (motion) {
        tft.setTextColor(C_RED);
        tft.setTextSize(2);
        tft.setCursor(85, sy - 4);
        tft.print("MOTION");
        // duration
        tft.setTextSize(1);
        tft.setTextColor(C_RED);
        tft.setCursor(84, sy + 18);
        uint32_t dur = (millis() - motionStart) / 1000;
        tft.printf("T+%02ds", dur);
    } else {
        tft.setTextColor(C_GREEN);
        tft.setTextSize(1);
        tft.setCursor(84, sy - 2);
        tft.print("SCANNING");
        // scanning animation dots
        static int dotCnt = 0;
        dotCnt = (dotCnt + 1) % 4;
        tft.setCursor(84, sy + 10);
        for (int d = 0; d < dotCnt; d++) tft.print(".");
    }

    // ── Box 3: Peak signal ───────────────────────────────────
    tft.fillRect(161, screenH - 42, 77, 40, C_BG);
    tft.setTextColor(C_CYAN);
    tft.setTextSize(2);
    tft.setCursor(164, sy - 4);
    tft.printf("%4d", peakSignal);
    tft.setTextSize(1);
    tft.setTextColor(C_GRID);
    tft.setCursor(164, sy + 18);
    tft.print("MAX SIG");

    // ── Box 4: Events ────────────────────────────────────────
    tft.fillRect(241, screenH - 42, 78, 40, C_BG);
    tft.setTextColor(eventCount > 0 ? C_YELLOW : C_GRID);
    tft.setTextSize(3);
    tft.setCursor(248, sy - 6);
    tft.printf("%03d", eventCount);
    tft.setTextSize(1);
    tft.setTextColor(C_GRID);
    tft.setCursor(244, sy + 18);
    tft.print("DETECTED");
}

// ─────────────────────────────────────────────────────────────
void setup() {
    delay(2000);
    Serial.begin(115200);
    Serial.println("=== BOOT OK ===");

    // FPGA UART — add wire tomorrow
    Serial2.begin(9600, SERIAL_8N1, -1, FPGA_TX);

    Wire.begin(I2C_SDA, I2C_SCL);
    Serial.println("I2C started");

    if (!ads.begin(0x48, &Wire)) {
        Serial.println("ERROR: ADS1115 not found!");
        adsOK = false;
    } else {
        Serial.println("ADS1115 OK");
        ads.setGain(GAIN_ONE);
        adsOK = true;
    }

    tft.init(240, 320);
    tft.setRotation(1);
    screenW = tft.width();
    screenH = tft.height();
    lastY   = (screenH - 56) / 2 + 25;

    drawStaticUI();
    tft.invertDisplay(false);

    if (!adsOK) {
        tft.setCursor(10, 50);
        tft.setTextColor(C_RED);
        tft.setTextSize(2);
        tft.print("ADS1115 NOT FOUND");
        tft.setCursor(10, 80);
        tft.print("Check wiring!");
    }

    // init history
    for (int i = 0; i < 20; i++) signalHistory[i] = 0;

    Serial.println("Setup done");
}

// ─────────────────────────────────────────────────────────────
void loop() {
    if (!adsOK) {
        Serial.println("ADS1115 missing");
        delay(2000);
        return;
    }

    // ══════════════════════════════════════════════════════════
    // ORIGINAL WORKING CODE — NOT CHANGED
    // ══════════════════════════════════════════════════════════
    int16_t rawVal = ads.readADC_SingleEnded(0);

    if (dynamicBaseline == 0.0) dynamicBaseline = rawVal;
    dynamicBaseline = (dynamicBaseline * 0.99) + (rawVal * 0.01);
    int16_t signal  = rawVal - (int16_t)dynamicBaseline;

    if (abs(signal) < 50) signal = 0;

    bool motionDetected = abs(signal) > threshold;

    if (DEBUG_MODE) {
        Serial.print("Raw:"); Serial.print(rawVal);
        Serial.print(" Base:"); Serial.print((int)dynamicBaseline);
        Serial.print(" Sig:"); Serial.print(signal);
        Serial.print(" Motion:"); Serial.println(motionDetected ? "YES" : "no");
    }

    int yPos = map(signal, -500, 500, screenH - 56, 25);
    yPos = constrain(yPos, 26, screenH - 57);

    tft.drawFastVLine(xPos + 2, 25, screenH - 81, C_BG);
    tft.drawFastVLine(xPos + 3, 25, screenH - 81, C_BG);
    if ((xPos + 2) % 40 == 0)
        for (int y = 25; y < screenH - 56; y += 3)
            tft.drawPixel(xPos + 2, y, C_GRID);

    uint16_t drawColor = motionDetected ? C_RED : C_GREEN;
    tft.drawLine(xPos - 1, lastY, xPos, yPos, drawColor);

    // ── Sweep indicator (2px bright bar ahead of draw pos) ───
    tft.drawFastVLine((xPos + 4) % screenW, 25, screenH - 81, C_BG);
    tft.drawFastVLine((xPos + 5) % screenW, 25, screenH - 81,
        motionDetected ? 0x3800 : 0x0060);

    lastY = yPos;
    xPos++;
    if (xPos >= screenW) xPos = 0;
    // ══════════════════════════════════════════════════════════
    // END ORIGINAL CODE
    // ══════════════════════════════════════════════════════════

    // ── New: track stats ─────────────────────────────────────
    lastSignal = abs(signal);
    if (lastSignal > peakSignal) peakSignal = lastSignal;

    // decay peak slowly
    if (millis() % 5000 < 2) peakSignal = max(0, peakSignal - 1);

    // event counter
    if (motionDetected && !wasMotion) {
        eventCount++;
        motionStart = millis();
    }
    wasMotion = motionDetected;

    // ── New: update info strip every 150ms ───────────────────
    if (millis() - lastInfoDraw >= 150) {
        lastInfoDraw = millis();
        updateInfoStrip(signal, motionDetected);
    }

    // ── New: send to FPGA every 100ms ────────────────────────
    // just add the wire tomorrow — code is ready
    if (millis() - lastFPGASend >= 100) {
        lastFPGASend = millis();
        Serial2.write(motionDetected ? 'M' : 'C');
        uint8_t str = (uint8_t)constrain(
            map(lastSignal, 0, 500, 0, 255), 0, 255);
        Serial2.write(str);
    }

    delay(2);
}