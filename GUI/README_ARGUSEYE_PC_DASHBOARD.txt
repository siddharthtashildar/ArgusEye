ARGUS-EYE PC RADAR DASHBOARD
============================

WHAT IT DOES
- Reads the ESP32-S3 telemetry over USB serial.
- Shows a scrolling signal graph, raw ADC, dynamic baseline, filtered AC signal,
  peak amplitude, motion state and event count.
- Supports session counters and exporting the visible graph buffer to CSV.
- Uses a dark dashboard UI; the TFT is not needed.

IMPORTANT
- Restore your original radar firmware in main.cpp before using the GUI.
- The firmware must print lines in this format (the original code already does):
    Raw:1234 Base:1230 Sig:4 Motion:no
- The original code uses Serial.begin(115200), so use 115200 baud in the GUI.
- Close PlatformIO's Serial Monitor before connecting the GUI. One program at a
  time can own the COM port.
- This GUI does not need the TFT connected. Do not change your existing radar
  sensor/ADS1115 wiring while switching to the PC display.

WINDOWS QUICK START
1. Install Python 3.10 or newer if not already installed.
2. Put arguseye_pc_dashboard.py and requirements_arguseye_gui.txt in the same folder.
3. Open a terminal in that folder and run:
       python -m venv .venv
       .venv\Scripts\activate
       python -m pip install -r requirements_arguseye_gui.txt
       python arguseye_pc_dashboard.py
4. Connect the ESP32, close PlatformIO Serial Monitor, and launch the app.
5. Select the ESP32's COM port (recently you saw COM4), choose 115200 baud, then
   click CONNECT.

TROUBLESHOOTING
- Port busy: close PlatformIO Serial Monitor and any other serial terminal.
- GUI connects but no samples appear: check that the original firmware is running
  and DEBUG_MODE is true. Look at SERIAL FEED for startup messages.
- No port listed: click REFRESH or check Windows Device Manager.
- Dashboard is only parsing telemetry lines matching Raw / Base / Sig / Motion.
