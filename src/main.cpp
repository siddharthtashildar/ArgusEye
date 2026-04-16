#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>

// ── Pins ──────────────────────────────────────────────────────
#define I2C_SDA 21
#define I2C_SCL 18
#define TFT_CS  9
#define TFT_DC  15
#define TFT_RST 14

// ── Tuning ────────────────────────────────────────────────────
int threshold = 30;
const bool DEBUG_MODE = true;   // keep true for now

// ── Colors ────────────────────────────────────────────────────
#define COLOR_BG      0x0000
#define COLOR_GRID    0x02AA
#define COLOR_SIGNAL  0x07E0
#define COLOR_ALERT   0xF800
#define COLOR_TEXT    0xFFFF
#define COLOR_HEADER  0x18E3

Adafruit_ADS1115 ads;
Adafruit_ST7789 tft = Adafruit_ST7789(TFT_CS, TFT_DC, TFT_RST);

int screenW, screenH;
int xPos = 0;
int lastY = 120;
float dynamicBaseline = 0.0;
bool adsOK = false;

void drawStaticUI() {
  tft.fillScreen(COLOR_BG);
  tft.fillRect(0, 0, screenW, 25, COLOR_HEADER);
  tft.setCursor(5, 5);
  tft.setTextColor(COLOR_TEXT);
  tft.setTextSize(2);
  tft.print("HB100 RADAR");
  for(int i = 30; i < screenW; i += 30)
    tft.drawFastVLine(i, 25, screenH - 25, COLOR_GRID);
  for(int i = 30; i < screenH; i += 30)
    tft.drawFastHLine(0, i, screenW, COLOR_GRID);
}

void setup() {
  delay(2000);
  Serial.begin(115200);
  Serial.println("=== BOOT OK ===");

  // I2C
  Wire.begin(I2C_SDA, I2C_SCL);
  Serial.println("I2C started");

  if (!ads.begin(0x48, &Wire)) {
    Serial.println("ERROR: ADS1115 not found!");
    Serial.println("Check SDA=GPIO1, SCL=GPIO2 wiring");
    adsOK = false;
  } else {
    Serial.println("ADS1115 OK");
    ads.setGain(GAIN_ONE);   // ±2.048V — correct for HB100
    adsOK = true;
  }

  // TFT
  tft.init(240, 320);
  tft.setRotation(1);
  screenW = tft.width();
  screenH = tft.height();
  lastY   = screenH / 2;
  drawStaticUI();
  tft.invertDisplay(false);

  if (!adsOK) {
    tft.setCursor(10, 50);
    tft.setTextColor(COLOR_ALERT);
    tft.setTextSize(2);
    tft.print("ADS1115 NOT FOUND");
    tft.setCursor(10, 80);
    tft.print("Check wiring!");

  }

  Serial.println("Setup done");
  
}

void loop() {
  if (!adsOK) {
    Serial.println("ADS1115 missing - check wiring");
    delay(2000);
    return;
  }

  // ── Read ────────────────────────────────────────────────────
  int16_t rawVal = ads.readADC_SingleEnded(0);

  // ── Baseline ────────────────────────────────────────────────
  if (dynamicBaseline == 0.0) dynamicBaseline = rawVal;
  dynamicBaseline = (dynamicBaseline * 0.99) + (rawVal * 0.01);
  int16_t signal  = rawVal - (int16_t)dynamicBaseline;

  // ── Noise gate ──────────────────────────────────────────────
  if (abs(signal) < 50) signal = 0;

  bool motionDetected = abs(signal) > threshold;

  if (DEBUG_MODE) {
    Serial.print("Raw:"); Serial.print(rawVal);
    Serial.print(" Base:"); Serial.print((int)dynamicBaseline);
    Serial.print(" Sig:"); Serial.print(signal);
    Serial.print(" Motion:"); Serial.println(motionDetected ? "YES" : "no");
  }

  // ── Draw ────────────────────────────────────────────────────
  int yPos = map(signal, -500, 500, screenH, 25);
  yPos = constrain(yPos, 26, screenH - 1);

  tft.drawFastVLine(xPos + 2, 25, screenH - 25, COLOR_BG);
  tft.drawFastVLine(xPos + 3, 25, screenH - 25, COLOR_BG);
  if ((xPos + 2) % 30 == 0)
    tft.drawFastVLine(xPos + 2, 25, screenH - 25, COLOR_GRID);

  uint16_t drawColor = motionDetected ? COLOR_ALERT : COLOR_SIGNAL;
  tft.drawLine(xPos - 1, lastY, xPos, yPos, drawColor);

  if (xPos % 15 == 0) {
    tft.fillRect(screenW - 110, 5, 105, 15, COLOR_HEADER);
    tft.setCursor(screenW - 105, 5);
    tft.setTextColor(motionDetected ? COLOR_ALERT : COLOR_TEXT);
    tft.setTextSize(1);
    tft.print(motionDetected ? ">> MOTION <<" : "SCANNING...");
  }

  lastY = yPos;
  xPos++;
  if (xPos >= screenW) xPos = 0;

  delay(2);
}