# ARGUS-EYE Experimental & Validation Protocol

This document outlines the standard physical experimental procedures required to evaluate the ARGUS-EYE radar system under real laboratory conditions.

---

## 1. Test Setup & Environmental Preparation

### 1.1 Equipment Placement
1. **Radar Sensor Mounting:** Mount the HB100 sensor firmly to a stable, non-vibrating support (tripod or bench clamp) at a height of **1.0 to 1.2 meters** above floor level.
2. **Antenna Orientation:** Point the radar aperture horizontally toward an open, unobstructed test area.
3. **Clearance Zone:** Ensure at least **4 meters of linear clearance** in front of the radar. Remove moving objects (e.g., oscillating fans, fluttering curtains, other personnel).
4. **Power Supply:** Power the ESP32-S3 and radar via a clean USB port or low-noise 5V power supply to minimize 50/60 Hz ripple into the high-gain LM358 amplifier.

```text
    +-----------------------------------------------------------+
    |                                                           |
    |   [Radar HB100]                                           |
    |      Height: 1.1 m                                        |
    |      Beam Angle: ~72° horizontal                          |
    |           \                                               |
    |            \                                              |
    |             \ <---- 1.0 m ----> [Zone 1]                  |
    |              \                                            |
    |               \ <---- 2.0 m ----> [Zone 2]                |
    |                \                                          |
    |                 \ <---- 3.0 m ----> [Zone 3]              |
    |                                                           |
    +-----------------------------------------------------------+
```

---

## 2. Experimental Test Scenarios

### Experiment 1: Stationary False Alarm Baseline (60 Seconds)
- **Objective:** Quantify background noise floor and verify the false alarm rate during stationary scenes.
- **Procedure:**
  1. Ensure no human or mechanical motion exists in the test room.
  2. In the dashboard, click **CALIBRATE** (measures quiet noise floor for 2.5 seconds).
  3. Start recording: Label `stationary_baseline`, Condition `stationary`.
  4. Record continuously for **60 seconds**.
- **Evaluation Criteria:**
  - False Alarms: $\le 1.0 \text{ per minute}$.
  - Noise floor stability: Envelope should remain $\le 25\text{ ADC counts}$.

### Experiment 2: Repeated Hand Gestures (Zone 1: 1.0 m)
- **Objective:** Measure sensitivity and detection latency for small-RCS targets moving at moderate speeds.
- **Procedure:**
  1. Stand at a distance of **1.0 meter** directly along the radar bore-sight.
  2. Keep body still. Perform **5 discrete hand-waving cycles** (wave hand back and forth for 2 seconds, pause still for 4 seconds between cycles).
  3. Record: Label `hand_gestures_1m`, Condition `hand_motion`.
- **Expected Metrics:**
  - Expected Doppler shift: $20 - 40\text{ Hz}$.
  - Target Recall: $\ge 90\%$.

### Experiment 3: Transverse Walking Across Field of View (Zone 2: 2.0 m)
- **Objective:** Evaluate beam-crossing detection and cross-sectional radar signature.
- **Procedure:**
  1. Walk perpendicularly across the radar beam from left to right at normal walking pace ($\sim 1.0 - 1.2\text{ m/s}$) at a distance of **2.0 meters**.
  2. Pause outside the beam for 4 seconds, then walk back from right to left.
  3. Repeat for **5 walking passes**.
  4. Record: Label `walking_transverse_2m`, Condition `walking`.
- **Expected Metrics:**
  - Peak Doppler shift: $55 - 85\text{ Hz}$.
  - Target Precision: $\ge 90\%$.
  - Median Latency: $\le 300\text{ ms}$.

### Experiment 4: Radial Walking (Towards and Away)
- **Objective:** Validate radial velocity tracking, amplitude swelling ($1/R^2$), and continuous hold-off logic.
- **Procedure:**
  1. Start at a distance of **3.5 meters** from the radar.
  2. Walk steadily toward the radar until reaching **0.8 meters**, pause 2 seconds, then walk backward to **3.5 meters**.
  3. Repeat for **3 complete trials**.
  4. Record: Label `walking_radial_approach`, Condition `walking`.

---

## 3. Ground Truth Annotation & Evaluation Execution

To evaluate a physical dataset:
1. Mark event timestamps in the recorded CSV column `ground_truth_motion` (1 during intentional movement, 0 during quiet pauses).
2. Run the quantitative evaluation benchmark tool:
   ```bash
   python research/run_evaluation.py --data-dir data/experiments
   ```
3. Inspect the resulting confusion matrix, precision, recall, false alarm rate, and median latency metrics.
