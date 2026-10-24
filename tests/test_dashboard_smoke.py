"""Smoke test for GUI Dashboard components in offscreen headless mode."""
import os
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Ensure Qt runs offscreen for testing without requiring a physical monitor
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from GUI.main import RadarDashboard


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_dashboard_initialization_and_packet_ingest(qapp):
    dashboard = RadarDashboard()
    assert dashboard is not None
    assert dashboard.windowTitle().startswith("ARGUS-EYE")

    # Ingest a simulated telemetry line
    dashboard.inbox.put((100.0, "Raw:12500 Base:12480 Sig:20 Motion:NO"))
    dashboard.process_incoming()

    assert dashboard.sample_count == 1
    assert dashboard.latest_raw == 12500
    assert dashboard.latest_baseline == 12480
    assert dashboard.latest_signal == 20

    # Ingest an extended telemetry packet
    dashboard.inbox.put((100.005, "Seq:2 T_us:10000 Dt:5000 Raw:12550 Base:12480 Sig:70 Motion:YES Filt:65 Env:68 Noise:15 Thresh:80 Det:1"))
    dashboard.process_incoming()

    assert dashboard.sample_count == 2
    assert dashboard.latest_raw == 12550
    assert dashboard.latest_firmware_motion is True
    assert dashboard.latest_envelope == 68

    dashboard.close()
