"""Tests for ARGUS-EYE Serial Protocol and Cadence Tracking."""
import pytest
from research.protocol import (
    parse_telemetry_line,
    CadenceTracker,
    format_command,
    TelemetryPacket,
)


def test_parse_legacy_telemetry_motion_no():
    line = "Raw:12345 Base:12340 Sig:5 Motion:no"
    pkt = parse_telemetry_line(line)
    assert pkt is not None
    assert pkt.raw == 12345
    assert pkt.baseline == 12340
    assert pkt.signal == 5
    assert pkt.firmware_motion is False
    assert pkt.is_extended is False


def test_parse_legacy_telemetry_motion_yes():
    line = "Raw:-250 Base:100 Sig:-350 Motion:YES"
    pkt = parse_telemetry_line(line)
    assert pkt is not None
    assert pkt.raw == -250
    assert pkt.baseline == 100
    assert pkt.signal == -350
    assert pkt.firmware_motion is True


def test_parse_extended_telemetry():
    line = "Seq:420 T_us:2100000 Dt:5000 Raw:12500 Base:12480 Sig:20 Motion:NO Filt:18 Env:22 Noise:14 Thresh:85 Det:1"
    pkt = parse_telemetry_line(line)
    assert pkt is not None
    assert pkt.seq == 420
    assert pkt.t_us == 2100000
    assert pkt.dt_us == 5000
    assert pkt.raw == 12500
    assert pkt.baseline == 12480
    assert pkt.signal == 20
    assert pkt.firmware_motion is False
    assert pkt.filtered == 18
    assert pkt.envelope == 22
    assert pkt.noise_floor == 14
    assert pkt.threshold == 85
    assert pkt.detector_mode == 1
    assert pkt.is_extended is True


def test_parse_malformed_lines():
    assert parse_telemetry_line("") is None
    assert parse_telemetry_line("=== BOOT OK ===") is None
    assert parse_telemetry_line("ADS1115 OK") is None
    assert parse_telemetry_line("Raw:abc Base:def Sig:0 Motion:NO") is None
    assert parse_telemetry_line("Random garbage line from noise") is None


def test_cadence_tracker_rate_and_loss():
    tracker = CadenceTracker(target_rate_hz=200.0)

    # Feed 20 evenly spaced packets at 200 Hz (5ms apart)
    t = 100.0
    for i in range(20):
        pkt = TelemetryPacket(
            raw=1000,
            baseline=1000,
            signal=0,
            firmware_motion=False,
            seq=i + 1,
            t_us=int(t * 1_000_000),
            dt_us=5000,
            rx_time=t,
        )
        tracker.update(pkt)
        t += 0.005

    diag = tracker.get_diagnostics()
    assert abs(diag["effective_rate_hz"] - 200.0) < 5.0
    assert diag["confirmed_lost_packets"] == 0
    assert diag["timing_anomalies"] == 0

    # Introduce a sequence gap (skip seq 21 to 24)
    pkt_jump = TelemetryPacket(
        raw=1000,
        baseline=1000,
        signal=0,
        firmware_motion=False,
        seq=25,
        t_us=int(t * 1_000_000),
        dt_us=25000,  # anomalous dt
        rx_time=t + 0.025,
    )
    tracker.update(pkt_jump)
    diag_jump = tracker.get_diagnostics()
    assert diag_jump["confirmed_lost_packets"] == 4
    assert diag_jump["timing_anomalies"] >= 1


def test_command_formatting():
    assert format_command("CAL") == "CMD:CAL\n"
    assert format_command("calibrate") == "CMD:CAL\n"
    assert format_command("RESET") == "CMD:RESET\n"
    assert format_command("SET_THRESH", 150) == "CMD:SET_THRESH=150\n"
    assert format_command("SET_DET", 1) == "CMD:SET_DET=1\n"
    assert format_command("PING") == "PING\n"
