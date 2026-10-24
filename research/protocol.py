"""ARGUS-EYE Serial Protocol Parser and Telemetry Tracker.
Handles both legacy and extended machine-parseable telemetry packets,
computes effective sample rates, and detects packet loss vs timing anomalies.
"""
from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional


@dataclass
class TelemetryPacket:
    raw: int
    baseline: int
    signal: int
    firmware_motion: bool
    seq: Optional[int] = None
    t_us: Optional[int] = None
    dt_us: Optional[int] = None
    filtered: Optional[int] = None
    envelope: Optional[int] = None
    noise_floor: Optional[int] = None
    threshold: Optional[int] = None
    detector_mode: Optional[int] = None
    is_extended: bool = False
    rx_time: float = 0.0


# Regex for legacy telemetry lines: "Raw:1234 Base:1230 Sig:4 Motion:YES"
LEGACY_RE = re.compile(
    r"Raw\s*:\s*([+-]?\d+)\s+Base\s*:\s*([+-]?\d+)\s+Sig\s*:\s*([+-]?\d+)\s+Motion\s*:\s*(YES|NO)",
    re.IGNORECASE,
)

# Regex for key-value extraction in extended packets
KV_RE = re.compile(r"([A-Za-z_]+)\s*:\s*([^\s]+)")


def parse_telemetry_line(line: str, rx_time: Optional[float] = None) -> Optional[TelemetryPacket]:
    """Parse one serial telemetry line.
    
    Compatible with:
    - Legacy format: "Raw:1234 Base:1230 Sig:4 Motion:no"
    - Extended format: "Seq:1042 T_us:5210000 Dt:4890 Raw:1234 Base:1230 Sig:4 Motion:no Filt:3 Env:5 Noise:12 Thresh:80 Det:1"
    
    Returns TelemetryPacket on success, None if the line does not contain radar telemetry.
    """
    if not line:
        return None
    
    if rx_time is None:
        rx_time = time.monotonic()
        
    leg_match = LEGACY_RE.search(line)
    if not leg_match:
        return None

    raw_val = int(leg_match.group(1))
    base_val = int(leg_match.group(2))
    sig_val = int(leg_match.group(3))
    mot_val = leg_match.group(4).upper() == "YES"

    # Check for extended key-values
    kv_matches = KV_RE.findall(line)
    kv_dict = {k.upper(): v for k, v in kv_matches}

    is_extended = "SEQ" in kv_dict or "T_US" in kv_dict

    seq = int(kv_dict["SEQ"]) if "SEQ" in kv_dict and kv_dict["SEQ"].isdigit() else None
    t_us = int(kv_dict["T_US"]) if "T_US" in kv_dict and kv_dict["T_US"].isdigit() else None
    dt_us = int(kv_dict["DT"]) if "DT" in kv_dict and kv_dict["DT"].isdigit() else None
    filtered = int(kv_dict["FILT"]) if "FILT" in kv_dict and kv_dict["FILT"].lstrip("-").isdigit() else None
    envelope = int(kv_dict["ENV"]) if "ENV" in kv_dict and kv_dict["ENV"].isdigit() else None
    noise = int(kv_dict["NOISE"]) if "NOISE" in kv_dict and kv_dict["NOISE"].isdigit() else None
    thresh = int(kv_dict["THRESH"]) if "THRESH" in kv_dict and kv_dict["THRESH"].isdigit() else None
    det_mode = int(kv_dict["DET"]) if "DET" in kv_dict and kv_dict["DET"].isdigit() else None

    return TelemetryPacket(
        raw=raw_val,
        baseline=base_val,
        signal=sig_val,
        firmware_motion=mot_val,
        seq=seq,
        t_us=t_us,
        dt_us=dt_us,
        filtered=filtered,
        envelope=envelope,
        noise_floor=noise,
        threshold=thresh,
        detector_mode=det_mode,
        is_extended=is_extended,
        rx_time=rx_time,
    )


class CadenceTracker:
    """Tracks sampling cadence, computes moving effective sample rate,
    and detects packet loss and timing jitter.
    """
    def __init__(self, target_rate_hz: float = 200.0, window_seconds: float = 2.0):
        self.target_rate_hz = target_rate_hz
        self.nominal_dt_s = 1.0 / target_rate_hz if target_rate_hz > 0 else 0.005
        self.window_seconds = window_seconds

        self.last_seq: Optional[int] = None
        self.last_t_us: Optional[int] = None
        self.last_rx_time: Optional[float] = None

        self.confirmed_lost_packets = 0
        self.timing_anomalies = 0
        self.total_packets_received = 0

        # Ring buffer of recent (timestamp_s) for rate calculation
        self._timestamps: deque[float] = deque(maxlen=2000)

    def update(self, packet: TelemetryPacket) -> None:
        self.total_packets_received += 1
        now_s = packet.rx_time if packet.rx_time > 0 else time.monotonic()
        self._timestamps.append(now_s)

        # Check sequence gaps for confirmed packet loss
        if packet.seq is not None:
            if self.last_seq is not None:
                gap = packet.seq - self.last_seq
                if gap > 1:
                    self.confirmed_lost_packets += (gap - 1)
            self.last_seq = packet.seq

        # Check timing anomalies (jitter exceeding +/- 50% nominal dt)
        if packet.dt_us is not None:
            nominal_us = self.nominal_dt_s * 1_000_000.0
            if packet.dt_us > (1.5 * nominal_us) or packet.dt_us < (0.5 * nominal_us):
                self.timing_anomalies += 1
        elif self.last_rx_time is not None:
            dt_s = now_s - self.last_rx_time
            if dt_s > (1.5 * self.nominal_dt_s) or dt_s < (0.5 * self.nominal_dt_s):
                self.timing_anomalies += 1

        self.last_rx_time = now_s
        if packet.t_us is not None:
            self.last_t_us = packet.t_us

    @property
    def effective_sample_rate(self) -> float:
        """Estimate sample rate from timestamps in the sliding window."""
        if len(self._timestamps) < 2:
            return 0.0
        oldest = self._timestamps[0]
        newest = self._timestamps[-1]
        dt = newest - oldest
        if dt <= 0.001:
            return 0.0
        return float((len(self._timestamps) - 1) / dt)

    def get_diagnostics(self) -> dict:
        return {
            "effective_rate_hz": round(self.effective_sample_rate, 1),
            "target_rate_hz": self.target_rate_hz,
            "packets_received": self.total_packets_received,
            "confirmed_lost_packets": self.confirmed_lost_packets,
            "timing_anomalies": self.timing_anomalies,
        }


def format_command(command: str, param: Optional[int | str] = None) -> str:
    """Format an outbound command string for the ESP32 serial interface."""
    cmd = command.strip().upper()
    if cmd in ("CAL", "CALIBRATE"):
        return "CMD:CAL\n"
    if cmd in ("RESET", "RST"):
        return "CMD:RESET\n"
    if cmd in ("STATUS", "GET_STATUS"):
        return "CMD:GET_STATUS\n"
    if cmd == "PING":
        return "PING\n"
    if cmd in ("SET_THRESH", "THRESH", "THRESHOLD"):
        return f"CMD:SET_THRESH={int(param)}\n"
    if cmd in ("SET_DET", "DET", "DETECTOR", "MODE"):
        return f"CMD:SET_DET={int(param)}\n"
    return f"CMD:{cmd}={param}\n" if param is not None else f"CMD:{cmd}\n"
