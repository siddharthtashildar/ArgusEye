# ArgusEye

ArgusEye is a motion-detection system built using an ESP32-S3, an HB100 Doppler radar sensor, ADS1115 ADC, LM358 amplifier, a 2.4-inch TFT display, and a Nexys A7 FPGA board.

The ESP32 performs signal acquisition, baseline tracking, and motion strength analysis. It also drives the TFT display and forwards motion status to the FPGA over UART for the 7-segment display.

## Project Structure

- `platformio.ini` — PlatformIO board configuration for the ESP32-S3
- `src/main.cpp` — ESP32 application code
- `vivado/top.v` — FPGA top module for UART reception and 7-segment display control
- `vivado/uart_rx.v` — FPGA UART receiver
- `vivado/nexys_a7.xdc` — Nexys A7 pin constraints

## Features

- Real-time radar waveform visualization on TFT
- Motion detection using ADS1115 raw ADC readings
- Signal strength meter and motion history graph
- UART link from ESP32 to FPGA for 7-segment display output
- Branded as `ArgusEye`

## Wiring

### ESP32 to ADS1115
- `ADS1115 VDD` → `ESP32 3.3V`
- `ADS1115 GND` → `ESP32 GND`
- `ADS1115 SDA` → `ESP32 GPIO21`
- `ADS1115 SCL` → `ESP32 GPIO18`
- `ADS1115 ADDR` → `GND`
- `ADS1115 A0` → LM358 output

### HB100 / LM358 / ADS1115 sensor chain
- `HB100 VCC` → `ESP32 VIN / 5V`
- `HB100 GND` → `GND`
- `HB100 IF` → `LM358 IN+` (pin 3)
- `LM358 VCC` → `ESP32 3.3V` (pin 8)
- `LM358 GND` → `GND` (pin 4)
- `LM358 IN-` (pin 2) → `GND` via 1kΩ resistor (Ri)
- `LM358 OUT` (pin 1) → `LM358 IN-` (pin 2) via 100kΩ resistor (Rf) for ~100x gain
- `LM358 OUT` (pin 1) → `ADS1115 A0`

### ESP32 to TFT
- `TFT MOSI` → `ESP32 GPIO11`
- `TFT SCLK` → `ESP32 GPIO12`
- `TFT CS` → `ESP32 GPIO9`
- `TFT DC` → `ESP32 GPIO15`
- `TFT RST` → `ESP32 GPIO14`
- `TFT VCC` → `ESP32 3.3V`
- `TFT GND` → `ESP32 GND`

### ESP32 to FPGA
- `ESP32 GPIO17` → `Nexys A7 uart_rx_pin` (JB pin 2)
- `ESP32 GND` → `Nexys A7 GND`

## Build and Flash

1. Install PlatformIO in Visual Studio Code.
2. Open the project folder.
3. Ensure the ESP32 board is selected in `platformio.ini`.
4. Build and upload via PlatformIO.

## Run

- Open the serial monitor at `115200` baud.
- The TFT should show the `ArgusEye` UI.
- Motion events are detected and logged to Serial.
- The FPGA 7-segment display shows motion state and strength over UART.

## Notes

- Use shared ground across ESP32, ADS1115, LM358, HB100, and FPGA.
- If you need more debug output, open the serial monitor and watch the startup and motion logs.
- `main.cpp` currently uses 400 Hz sampling and a block-based motion detection algorithm.

## License

This repository contains project source code for educational and prototyping use.
