# ARGUS-EYE Serial Communication Protocol Specification

## 1. Overview
The ARGUS-EYE firmware communicates with the host PC over USB serial at **115,200 baud, 8-N-1**.
The protocol is designed with two core principles:
1. **100% Backward Compatibility:** Legacy PC dashboards matching `Raw:<val> Base:<val> Sig:<val> Motion:<YES/NO>` continue parsing without modification.
2. **Machine-Parseable Extensibility:** Additional diagnostics, microsecond timestamps, sample sequence indices, and intermediate DSP states are appended as structured key-value tokens.

---

## 2. Telemetry Packet Format (ESP32 → PC)

### 2.1 Packet Line Syntax
```text
Seq:<uint> T_us:<uint> Dt:<uint> Raw:<int> Base:<int> Sig:<int> Motion:<YES|NO> Filt:<int> Env:<int> Noise:<int> Thresh:<int> Det:<0|1>
```

### 2.2 Field Descriptions
| Field Token | Type | Units / Range | Description |
|---|---|---|---|
| `Seq` | uint32 | 1 to $2^{32}-1$ | Monotonically increasing sample sequence counter. Used to detect packet drops. |
| `T_us` | uint32 | $\mu\text{s}$ | Microsecond timestamp from `micros()`. |
| `Dt` | uint32 | $\mu\text{s}$ | Elapsed interval since previous sample. Nominal is $5000\ \mu\text{s}$ (200 Hz). |
| `Raw` | int16 | -32768 to 32767 | Unmodified 16-bit ADC conversion from ADS1115 A0. |
| `Base` | int16 | -32768 to 32767 | Dynamically tracked DC baseline (EMA, $\alpha=0.01$). |
| `Sig` | int16 | -32768 to 32767 | Signed AC signal: $S = \text{Raw} - \text{Base}$. |
| `Motion` | string | `YES` or `NO` | Motion detection status from the currently selected detector. |
| `Filt` | int16 | -32768 to 32767 | Causal band-pass filtered signal (5 - 80 Hz passband). |
| `Env` | int16 | 0 to 32767 | Causal leaky peak envelope follower output. |
| `Noise` | int16 | 0 to 32767 | Quiet background noise floor estimate. |
| `Thresh`| int16 | 0 to 32767 | Active trigger threshold in ADC counts. |
| `Det` | uint8 | `0` or `1` | Active detector mode (`0` = Legacy Deadband, `1` = Adaptive Causal). |

### 2.3 Example Telemetry Stream
```text
Seq:1040 T_us:5200000 Dt:5000 Raw:12480 Base:12480 Sig:0 Motion:NO Filt:0 Env:8 Noise:10 Thresh:80 Det:1
Seq:1041 T_us:5205000 Dt:5000 Raw:12620 Base:12481 Sig:139 Motion:NO Filt:135 Env:48 Noise:10 Thresh:80 Det:1
Seq:1042 T_us:5210000 Dt:5000 Raw:12740 Base:12483 Sig:257 Motion:NO Filt:249 Env:118 Noise:10 Thresh:80 Det:1
Seq:1043 T_us:5215000 Dt:5000 Raw:12810 Base:12486 Sig:324 Motion:YES Filt:312 Env:186 Noise:10 Thresh:80 Det:1
```

---

## 3. Command Protocol (PC → ESP32)

Commands are sent from the host PC as ASCII text strings terminated with a newline (`\n` or `\r\n`).

### 3.1 Supported Commands
| Command String | Parameters | Description | Firmware Response |
|---|---|---|---|
| `CMD:SET_THRESH=<val>` | Integer (10 - 5000) | Sets the trigger sensitivity threshold in ADC counts. | `[ACK] Threshold set to <val> ADC` |
| `CMD:SET_DET=<mode>` | `0` or `1` | Sets active detector (`0` = Legacy Deadband, `1` = Adaptive). | `[ACK] Detector mode set to <MODE>` |
| `CMD:CAL` or `CAL` | None | Starts a 2000 ms quiet baseline and noise floor calibration. | `[ACK] Calibration started...` |
| `CMD:RESET` or `RST` | None | Resets sample counters, baseline, and event accumulators. | `[ACK] Radar DSP and event counters reset` |
| `CMD:GET_STATUS` | None | Requests diagnostic status packet. | `[STATUS] Mode:... Thresh:... Rate:...` |
| `PING` | None | Verifies active serial communication link. | `PONG` |
