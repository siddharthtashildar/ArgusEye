"""ARGUS-EYE | Cyberpunk-Inspired Research & Engineering Radar Console.

Integrates real-time ESP32-S3 telemetry acquisition, adaptive signal processing,
PSD/spectrogram analysis, dataset recording, and quantitative motion evaluation.
"""
from __future__ import annotations

import csv
import queue
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pyqtgraph as pg
import serial
from serial.tools import list_ports
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from research.protocol import (
    parse_telemetry_line,
    CadenceTracker,
    format_command,
    TelemetryPacket,
)
from research.dsp_pipeline import (
    RadarDSPPipeline,
    detect_motion_adaptive,
    detect_motion_legacy,
    compute_envelope_causal,
    butter_bandpass_filter,
    estimate_baseline,
)
from research.spectral_analysis import (
    compute_welch_psd,
    compute_spectrogram,
    doppler_to_velocity,
)
from research.evaluation import evaluate_detections, EvaluationResult
from research.recorder import SessionRecorder, load_recording

APP_TITLE = "ARGUS-EYE // DOPPLER RADAR CONSOLE"
BAUD_DEFAULT = 115200
PLOT_SAMPLES = 720
INBOX_LIMIT = 2000
PROCESS_INTERVAL_MS = 12
PLOT_INTERVAL_MS = 33

# Cyberpunk-inspired Palette
BG = "#08090c"
PANEL = "#101217"
PANEL_ALT = "#151820"
EDGE = "#292c36"
TEXT = "#f2f4f8"
MUTED = "#868a98"
YELLOW = "#fcee0a"
CYAN = "#00e5ff"
MAGENTA = "#ff2a6d"
PURPLE = "#b78aff"
GREEN = "#05ffa1"


class SerialReader(threading.Thread):
    """Isolated high-priority serial I/O thread."""
    def __init__(self, port: serial.Serial, inbox: queue.Queue):
        super().__init__(daemon=True, name="ArgusEyeSerialReader")
        self.port = port
        self.inbox = inbox
        self.stop_event = threading.Event()
        self.dropped = 0

    def _publish(self, item: tuple[float, str]) -> None:
        try:
            self.inbox.put_nowait(item)
        except queue.Full:
            try:
                self.inbox.get_nowait()
                self.dropped += 1
            except queue.Empty:
                pass
            try:
                self.inbox.put_nowait(item)
            except queue.Full:
                self.dropped += 1

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                line_bytes = self.port.readline()
                if line_bytes:
                    line = line_bytes.decode("utf-8", errors="replace").strip()
                    if line:
                        self._publish((time.monotonic(), line))
            except (serial.SerialException, OSError) as exc:
                if not self.stop_event.is_set():
                    self._publish((time.monotonic(), f"[SERIAL ERROR] {exc}"))
                break
            except Exception as exc:
                if not self.stop_event.is_set():
                    self._publish((time.monotonic(), f"[READ ERROR] {exc}"))
                break

    def stop(self) -> None:
        self.stop_event.set()


class MetricCard(QFrame):
    def __init__(self, eyebrow: str, initial: str, accent: str, detail: str):
        super().__init__()
        self.setObjectName("metricCard")
        self.setMinimumHeight(76)
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 9, 14, 8)
        box.setSpacing(2)
        title = QLabel(eyebrow)
        title.setObjectName("metricLabel")
        self.value = QLabel(initial)
        self.value.setObjectName("metricValue")
        self.value.setStyleSheet(f"color: {accent};")
        self.detail = QLabel(detail)
        self.detail.setObjectName("metricDetail")
        box.addWidget(title)
        box.addWidget(self.value)
        box.addWidget(self.detail)

    def set_value(self, value: str, detail: Optional[str] = None) -> None:
        self.value.setText(value)
        if detail is not None:
            self.detail.setText(detail)


class SpectralAnalysisDialog(QDialog):
    """Offline analysis dialog displaying Welch PSD and STFT Spectrogram."""
    def __init__(self, parent: QWidget, signals: Dict[str, np.ndarray], fs: float = 200.0, title: str = "Spectral Analysis"):
        super().__init__(parent)
        self.setWindowTitle(f"ARGUS-EYE // {title}")
        self.resize(1000, 700)
        self.setStyleSheet(f"background: {BG}; color: {TEXT}; font-family: 'Segoe UI';")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        # Header info
        head = QHBoxLayout()
        title_lbl = QLabel(title.upper())
        title_lbl.setStyleSheet(f"font-size: 16px; font-weight: 900; color: {YELLOW};")
        head.addWidget(title_lbl)
        head.addStretch(1)
        dur = signals["elapsed_s"][-1] - signals["elapsed_s"][0] if len(signals["elapsed_s"]) > 1 else 0.0
        info_lbl = QLabel(f"SAMPLES: {len(signals['elapsed_s']):,}  ·  FS: {fs:.1f} Hz  ·  DURATION: {dur:.1f}s")
        info_lbl.setStyleSheet(f"color: {MUTED}; font-family: Consolas; font-size: 11px;")
        head.addWidget(info_lbl)
        layout.addLayout(head)

        splitter = QSplitter(Qt.Vertical)

        # 1. Welch PSD Plot Widget
        psd_frame = QFrame()
        psd_frame.setObjectName("panel")
        psd_frame.setStyleSheet(f"background: {PANEL}; border: 1px solid {EDGE}; border-radius: 4px;")
        psd_layout = QVBoxLayout(psd_frame)
        psd_layout.setContentsMargins(10, 8, 10, 8)
        psd_label = QLabel("WELCH POWER SPECTRAL DENSITY (PSD)")
        psd_label.setStyleSheet(f"color: {CYAN}; font-size: 11px; font-weight: 800;")
        psd_layout.addWidget(psd_label)

        self.psd_plot = pg.PlotWidget(background="#0b0d11")
        self.psd_plot.showGrid(x=True, y=True, alpha=0.2)
        self.psd_plot.setLabel("bottom", "Doppler Frequency", units="Hz", **{"color": MUTED})
        self.psd_plot.setLabel("left", "Power Density", units="dB", **{"color": MUTED})
        self.psd_curve = self.psd_plot.plot(pen=pg.mkPen(CYAN, width=1.8))
        psd_layout.addWidget(self.psd_plot)
        splitter.addWidget(psd_frame)

        # 2. Spectrogram (STFT) Image View
        spec_frame = QFrame()
        spec_frame.setObjectName("panel")
        spec_frame.setStyleSheet(f"background: {PANEL}; border: 1px solid {EDGE}; border-radius: 4px;")
        spec_layout = QVBoxLayout(spec_frame)
        spec_layout.setContentsMargins(10, 8, 10, 8)
        spec_label = QLabel("STFT DOPPLER SPECTROGRAM (FREQUENCY vs TIME)")
        spec_label.setStyleSheet(f"color: {PURPLE}; font-size: 11px; font-weight: 800;")
        spec_layout.addWidget(spec_label)

        self.spec_plot = pg.PlotWidget(background="#0b0d11")
        self.spec_plot.setLabel("bottom", "Time", units="s", **{"color": MUTED})
        self.spec_plot.setLabel("left", "Doppler Frequency", units="Hz", **{"color": MUTED})
        self.img_item = pg.ImageItem()
        self.spec_plot.addItem(self.img_item)
        spec_layout.addWidget(self.spec_plot)
        splitter.addWidget(spec_frame)

        layout.addWidget(splitter, 1)

        # Compute and render spectral data
        ac_sig = signals.get("ac_signal", signals.get("raw_adc", np.zeros(10)))
        freqs, psd_db = compute_welch_psd(ac_sig, fs=fs, nperseg=256)
        self.psd_curve.setData(freqs, psd_db)

        times, s_freqs, sxx_db = compute_spectrogram(ac_sig, fs=fs, nperseg=128, noverlap=96)
        # Apply colormap to spectrogram
        sxx_norm = np.clip((sxx_db - np.min(sxx_db)) / max(1.0, np.ptp(sxx_db)), 0.0, 1.0)
        self.img_item.setImage(sxx_norm.T)
        self.img_item.setRect(pg.QtCore.QRectF(times[0], s_freqs[0], times[-1] - times[0], s_freqs[-1] - s_freqs[0]))

        # Close button
        btn_bar = QHBoxLayout()
        btn_bar.addStretch(1)
        close_btn = QPushButton("CLOSE")
        close_btn.setStyleSheet(f"background: {PANEL_ALT}; color: {TEXT}; border: 1px solid {EDGE}; padding: 6px 16px;")
        close_btn.clicked.connect(self.accept)
        btn_bar.addWidget(close_btn)
        layout.addLayout(btn_bar)


class RadarDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1380, 880)
        self.setMinimumSize(1080, 720)

        # Communication & Reader
        self.serial_port: Optional[serial.Serial] = None
        self.reader: Optional[SerialReader] = None
        self.inbox: queue.Queue = queue.Queue(maxsize=INBOX_LIMIT)
        self.cadence = CadenceTracker(target_rate_hz=200.0)

        # Telemetry State
        self.connected_at: Optional[float] = None
        self.session_clock_started = time.monotonic()
        self.sample_count = 0
        self.event_count = 0
        self.peak_magnitude = 0
        self.latest_raw = 0
        self.latest_baseline = 0
        self.latest_signal = 0
        self.latest_filtered = 0
        self.latest_envelope = 0
        self.latest_noise_floor = 15
        self.latest_firmware_motion = False
        self.latest_selected_motion = False
        self.last_selected_motion = False
        self.pc_motion_active = False
        self.envelope_pc = 0.0
        self.above_count = 0
        self.below_count = 0

        # UI Throttling and Plots
        self.plot_paused = False
        self.calibration_deadline: Optional[float] = None
        self.calibration_samples: List[float] = []
        self.last_ui_update = 0.0

        # History buffers (bounded memory)
        self.signal_history: deque[float] = deque(maxlen=PLOT_SAMPLES)
        self.filtered_history: deque[float] = deque(maxlen=PLOT_SAMPLES)
        self.motion_history: deque[bool] = deque(maxlen=PLOT_SAMPLES)
        self.log_lines: deque[str] = deque(maxlen=8)

        # Recording
        self.recorder = SessionRecorder()
        self.session_rows: List[dict] = []

        self._build_ui()
        self._apply_styles()
        self.refresh_ports()

        # Timers
        self.process_timer = QTimer(self)
        self.process_timer.timeout.connect(self.process_incoming)
        self.process_timer.start(PROCESS_INTERVAL_MS)

        self.plot_timer = QTimer(self)
        self.plot_timer.timeout.connect(self.render_plot)
        self.plot_timer.start(PLOT_INTERVAL_MS)

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_session_clock)
        self.clock_timer.start(250)

    # ---------------------------- UI Construction ----------------------------
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 12, 18, 12)
        outer.setSpacing(10)

        # Header bar
        header = QHBoxLayout()
        header.setSpacing(12)
        logo = QLabel("A//E")
        logo.setObjectName("logo")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedSize(54, 46)
        header.addWidget(logo)

        brand_col = QVBoxLayout()
        brand_col.setSpacing(1)
        wordmark = QLabel("ARGUS-EYE")
        wordmark.setObjectName("wordmark")
        tagline = QLabel("DOPPLER RADAR MOTION DETECTOR  /  10.525 GHz CW INTELLIGENCE")
        tagline.setObjectName("tagline")
        brand_col.addWidget(wordmark)
        brand_col.addWidget(tagline)
        header.addLayout(brand_col)
        header.addStretch(1)

        self.header_clock = QLabel("SESSION 00:00:00")
        self.header_clock.setObjectName("headerClock")
        header.addWidget(self.header_clock, alignment=Qt.AlignVCenter)

        self.connection_badge = QLabel("●  OFFLINE")
        self.connection_badge.setObjectName("connectionBadge")
        self.connection_badge.setProperty("state", "offline")
        header.addWidget(self.connection_badge, alignment=Qt.AlignVCenter)
        outer.addLayout(header)

        # Connection Bar
        conn_panel = QFrame()
        conn_panel.setObjectName("panel")
        conn = QHBoxLayout(conn_panel)
        conn.setContentsMargins(12, 8, 12, 8)
        conn.setSpacing(8)
        conn.addWidget(self._eyebrow("PORT"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(210)
        conn.addWidget(self.port_combo)

        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setObjectName("iconButton")
        self.refresh_btn.setFixedWidth(34)
        self.refresh_btn.clicked.connect(self.refresh_ports)
        conn.addWidget(self.refresh_btn)

        conn.addSpacing(6)
        conn.addWidget(self._eyebrow("BAUD"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200", "9600"])
        self.baud_combo.setCurrentText(str(BAUD_DEFAULT))
        self.baud_combo.setFixedWidth(90)
        conn.addWidget(self.baud_combo)

        self.connect_btn = QPushButton("CONNECT  ↗")
        self.connect_btn.setObjectName("primaryButton")
        self.connect_btn.clicked.connect(self.toggle_connection)
        conn.addWidget(self.connect_btn)

        conn.addStretch(1)
        self.link_detail = QLabel("Connect ESP32 · Non-blocking paced telemetry at 200 Hz")
        self.link_detail.setObjectName("mutedText")
        conn.addWidget(self.link_detail)
        outer.addWidget(conn_panel)

        # 4 Metric Cards
        metrics = QHBoxLayout()
        metrics.setSpacing(9)
        self.raw_card = MetricCard("RAW ADC / BASELINE", "—", TEXT, "DC LEVEL: —")
        self.signal_card = MetricCard("AC SIGNAL / ENVELOPE", "—", CYAN, "LEAKY ENVELOPE: —")
        self.noise_card = MetricCard("NOISE / THRESHOLD", "—", PURPLE, "TRIGGER: —  ·  RELEASE: —")
        self.rate_card = MetricCard("SAMPLE CADENCE", "0.0 Hz", GREEN, "LOSS: 0  ·  JITTER: 0")
        for c in (self.raw_card, self.signal_card, self.noise_card, self.rate_card):
            metrics.addWidget(c, 1)
        outer.addLayout(metrics)

        # Main Body: Plot (left) + Tracking Info (right)
        body = QHBoxLayout()
        body.setSpacing(10)

        graph_panel = QFrame()
        graph_panel.setObjectName("panel")
        graph_layout = QVBoxLayout(graph_panel)
        graph_layout.setContentsMargins(14, 11, 14, 10)
        graph_layout.setSpacing(7)

        graph_head = QHBoxLayout()
        graph_title_col = QVBoxLayout()
        graph_title_col.setSpacing(1)
        graph_title = QLabel("REAL-TIME SIGNAL TRACE")
        graph_title.setObjectName("sectionTitle")
        graph_subtitle = QLabel("FILTERED AC DOPPLER WAVEFORM  /  DYNAMIC THRESHOLD OVERLAYS")
        graph_subtitle.setObjectName("subtleText")
        graph_title_col.addWidget(graph_title)
        graph_title_col.addWidget(graph_subtitle)
        graph_head.addLayout(graph_title_col)
        graph_head.addStretch(1)

        self.sample_label = QLabel("0 SAMPLES")
        self.sample_label.setObjectName("microBadge")
        graph_head.addWidget(self.sample_label)
        graph_layout.addLayout(graph_head)

        pg.setConfigOptions(antialias=True, foreground=MUTED, background="#0b0d11")
        self.plot = pg.PlotWidget(background="#0b0d11")
        self.plot.setObjectName("signalPlot")
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.plot.setLabel("left", "AMPLITUDE", units="ADC", **{"color": MUTED})
        self.plot.setLabel("bottom", "SAMPLE WINDOW", **{"color": MUTED})
        self.plot.setXRange(0, PLOT_SAMPLES, padding=0)
        self.plot.setYRange(-200, 200, padding=0)
        item = self.plot.getPlotItem()
        item.setMenuEnabled(False)
        item.hideButtons()
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setClipToView(True)

        # Plot curves & threshold lines
        self.zero_line = pg.InfiniteLine(
            pos=0, angle=0,
            pen=pg.mkPen(color=(120, 126, 140, 110), width=1, style=Qt.PenStyle.DashLine),
        )
        self.trigger_pos = pg.InfiniteLine(
            pos=120, angle=0,
            pen=pg.mkPen(color=YELLOW, width=1.2, style=Qt.PenStyle.DotLine),
        )
        self.trigger_neg = pg.InfiniteLine(
            pos=-120, angle=0,
            pen=pg.mkPen(color=YELLOW, width=1.2, style=Qt.PenStyle.DotLine),
        )
        self.release_pos = pg.InfiniteLine(
            pos=78, angle=0,
            pen=pg.mkPen(color=(252, 238, 10, 80), width=1, style=Qt.PenStyle.DashLine),
        )
        self.release_neg = pg.InfiniteLine(
            pos=-78, angle=0,
            pen=pg.mkPen(color=(252, 238, 10, 80), width=1, style=Qt.PenStyle.DashLine),
        )
        for line in (self.zero_line, self.trigger_pos, self.trigger_neg, self.release_pos, self.release_neg):
            self.plot.addItem(line)

        self.quiet_curve = self.plot.plot(pen=pg.mkPen(CYAN, width=1.8))
        self.motion_curve = self.plot.plot(pen=pg.mkPen(MAGENTA, width=2.2))
        graph_layout.addWidget(self.plot, 1)

        legend = QHBoxLayout()
        legend.addWidget(self._legend(CYAN, "SCANNING"))
        legend.addSpacing(10)
        legend.addWidget(self._legend(MAGENTA, "MOTION"))
        legend.addSpacing(10)
        legend.addWidget(self._legend(YELLOW, "TRIGGER"))
        legend.addSpacing(10)
        legend.addWidget(self._legend("#a09020", "RELEASE"))
        legend.addStretch(1)
        self.graph_status = QLabel("WAITING FOR TELEMETRY")
        self.graph_status.setObjectName("subtleText")
        legend.addWidget(self.graph_status)
        graph_layout.addLayout(legend)
        body.addWidget(graph_panel, 7)

        # Right Tracking Status Panel
        side_panel = QFrame()
        side_panel.setObjectName("panel")
        side_panel.setMinimumWidth(240)
        side_panel.setMaximumWidth(310)
        side = QVBoxLayout(side_panel)
        side.setContentsMargins(14, 12, 14, 12)
        side.setSpacing(9)

        side.addWidget(self._eyebrow("DETECTION STATE"))
        self.motion_state = QLabel("STANDBY")
        self.motion_state.setObjectName("motionState")
        self.motion_state.setAlignment(Qt.AlignCenter)
        self.motion_state.setMinimumHeight(68)
        self.motion_state.setProperty("state", "idle")
        side.addWidget(self.motion_state)

        self.motion_desc = QLabel("Connect the ESP32 to begin live monitoring.")
        self.motion_desc.setObjectName("mutedText")
        self.motion_desc.setWordWrap(True)
        side.addWidget(self.motion_desc)

        side.addWidget(self._divider())

        env_head = QHBoxLayout()
        env_head.addWidget(self._eyebrow("SIGNAL ENVELOPE"))
        env_head.addStretch(1)
        self.envelope_readout = QLabel("0 ADC")
        self.envelope_readout.setObjectName("inlineValue")
        env_head.addWidget(self.envelope_readout)
        side.addLayout(env_head)

        self.signal_meter = QProgressBar()
        self.signal_meter.setRange(0, 1000)
        self.signal_meter.setValue(0)
        self.signal_meter.setTextVisible(False)
        self.signal_meter.setFixedHeight(8)
        side.addWidget(self.signal_meter)

        self.meter_scale = QLabel("0        250        500        1000+")
        self.meter_scale.setObjectName("microText")
        side.addWidget(self.meter_scale)

        side.addWidget(self._divider())

        stats_grid = QHBoxLayout()
        stats_grid.setSpacing(8)
        self.events_value, events_box = self._mini_stat("EVENTS", "0", YELLOW)
        self.peak_value, peak_box = self._mini_stat("PEAK", "0", PURPLE)
        stats_grid.addWidget(events_box, 1)
        stats_grid.addWidget(peak_box, 1)
        side.addLayout(stats_grid)

        self.firmware_state = QLabel("DEVICE FLAG  /  —")
        self.firmware_state.setObjectName("microBadge")
        side.addWidget(self.firmware_state)

        side.addStretch(1)
        self.rate_label = QLabel("0.0 SAMPLES/S  ·  QUEUE 0")
        self.rate_label.setObjectName("microText")
        side.addWidget(self.rate_label)
        body.addWidget(side_panel, 3)
        outer.addLayout(body, 1)

        # Control Bar: Sensitivity, Detector, Calibrate, Recording, Analysis
        ctrl_panel = QFrame()
        ctrl_panel.setObjectName("panel")
        ctrl = QHBoxLayout(ctrl_panel)
        ctrl.setContentsMargins(12, 8, 12, 8)
        ctrl.setSpacing(9)

        ctrl.addWidget(self._eyebrow("DETECTOR"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "Firmware Adaptive",
            "Firmware Legacy",
            "PC Adaptive Causal",
            "PC Legacy Baseline",
        ])
        self.mode_combo.currentIndexChanged.connect(self.on_detector_mode_changed)
        self.mode_combo.setFixedWidth(150)
        ctrl.addWidget(self.mode_combo)

        ctrl.addSpacing(6)
        ctrl.addWidget(self._eyebrow("TRIGGER"))
        self.threshold_slider = QSlider(Qt.Horizontal)
        self.threshold_slider.setRange(30, 800)
        self.threshold_slider.setValue(120)
        self.threshold_slider.setMinimumWidth(110)
        self.threshold_slider.valueChanged.connect(self.on_threshold_changed)
        ctrl.addWidget(self.threshold_slider)

        self.threshold_value = QLabel("120 ADC")
        self.threshold_value.setObjectName("inlineValue")
        self.threshold_value.setMinimumWidth(60)
        ctrl.addWidget(self.threshold_value)

        self.calibrate_btn = QPushButton("CALIBRATE")
        self.calibrate_btn.setObjectName("secondaryButton")
        self.calibrate_btn.setToolTip("Trigger 2-second quiet baseline and noise floor measurement")
        self.calibrate_btn.clicked.connect(self.start_calibration)
        ctrl.addWidget(self.calibrate_btn)

        # Recording controls
        self.rec_btn = QPushButton("RECORD ●")
        self.rec_btn.setObjectName("recordButton")
        self.rec_btn.clicked.connect(self.toggle_recording)
        ctrl.addWidget(self.rec_btn)

        # Spectral Analysis button
        self.analysis_btn = QPushButton("SPECTRAL VIEW ∿")
        self.analysis_btn.setObjectName("secondaryButton")
        self.analysis_btn.clicked.connect(self.open_spectral_analysis)
        ctrl.addWidget(self.analysis_btn)

        # Offline Replay / Load CSV
        self.load_btn = QPushButton("LOAD CSV 📂")
        self.load_btn.setObjectName("secondaryButton")
        self.load_btn.clicked.connect(self.load_recording_file)
        ctrl.addWidget(self.load_btn)

        self.pause_btn = QPushButton("PAUSE TRACE")
        self.pause_btn.setObjectName("secondaryButton")
        self.pause_btn.clicked.connect(self.toggle_plot_pause)
        ctrl.addWidget(self.pause_btn)

        self.reset_btn = QPushButton("RESET")
        self.reset_btn.setObjectName("quietButton")
        self.reset_btn.clicked.connect(self.clear_session)
        ctrl.addWidget(self.reset_btn)

        outer.addWidget(ctrl_panel)

        # Activity Log
        log_panel = QFrame()
        log_panel.setObjectName("logPanel")
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(11, 6, 11, 6)
        log_layout.setSpacing(4)
        log_header = QHBoxLayout()
        log_header.addWidget(self._eyebrow("SYSTEM ACTIVITY"))
        log_header.addStretch(1)
        self.log_state = QLabel("READY")
        self.log_state.setObjectName("microText")
        log_header.addWidget(self.log_state)
        log_layout.addLayout(log_header)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(8)
        self.log_view.setFixedHeight(54)
        self.log_view.setPlaceholderText("Serial telemetry, DSP events, and recording notifications.")
        log_layout.addWidget(self.log_view)
        outer.addWidget(log_panel)

        self.statusBar().showMessage("READY  /  Select serial port and connect to begin")

    def _eyebrow(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("eyebrow")
        return l

    def _legend(self, color: str, text: str) -> QLabel:
        l = QLabel(f"●  {text}")
        l.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: 700;")
        return l

    def _divider(self) -> QFrame:
        d = QFrame()
        d.setObjectName("divider")
        d.setFixedHeight(1)
        d.setStyleSheet(f"background: {EDGE};")
        return d

    def _mini_stat(self, label_text: str, value_text: str, accent: str):
        panel = QFrame()
        panel.setObjectName("miniStat")
        box = QVBoxLayout(panel)
        box.setContentsMargins(8, 6, 8, 6)
        box.setSpacing(2)
        title = QLabel(label_text)
        title.setObjectName("microText")
        value = QLabel(value_text)
        value.setObjectName("miniStatValue")
        value.setStyleSheet(f"color: {accent}; font-family: Consolas; font-size: 16px; font-weight: 800;")
        box.addWidget(title)
        box.addWidget(value)
        return value, panel

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"""
            QWidget#root {{ background: {BG}; color: {TEXT}; font-family: 'Segoe UI'; font-size: 11px; }}
            QLabel {{ color: {TEXT}; }}
            QLabel#logo {{ background: {YELLOW}; color: #08090c; font-family: Consolas; font-size: 16px; font-weight: 900; border-radius: 2px; }}
            QLabel#wordmark {{ color: {TEXT}; font-size: 22px; font-weight: 900; letter-spacing: 1.2px; }}
            QLabel#tagline {{ color: {MUTED}; font-size: 9px; letter-spacing: 1.4px; }}
            QLabel#headerClock {{ color: {MUTED}; font-family: Consolas; font-size: 10px; padding-right: 8px; }}
            QFrame#panel, QFrame#metricCard, QFrame#logPanel {{ background: {PANEL}; border: 1px solid {EDGE}; border-radius: 4px; }}
            QFrame#miniStat {{ background: {PANEL_ALT}; border: 1px solid #282b34; border-radius: 3px; }}
            QLabel#eyebrow, QLabel#metricLabel {{ color: {MUTED}; font-size: 9px; font-weight: 800; letter-spacing: 1.2px; }}
            QLabel#metricValue {{ font-family: Consolas; font-size: 21px; font-weight: 800; }}
            QLabel#metricDetail, QLabel#subtleText {{ color: #767a86; font-size: 9px; letter-spacing: .4px; }}
            QLabel#mutedText {{ color: {MUTED}; font-size: 10px; }}
            QLabel#microText {{ color: #767a86; font-family: Consolas; font-size: 9px; }}
            QLabel#inlineValue {{ color: {YELLOW}; font-family: Consolas; font-size: 11px; font-weight: 800; }}
            QLabel#microBadge {{ color: {YELLOW}; background: #22220e; border: 1px solid #5b5813; padding: 4px 7px; font-family: Consolas; font-size: 9px; font-weight: 700; }}
            QLabel#connectionBadge {{ color: {MAGENTA}; background: #24121a; border: 1px solid #612436; padding: 6px 10px; font-family: Consolas; font-size: 9px; font-weight: 800; }}
            QLabel#connectionBadge[state="online"] {{ color: {CYAN}; background: #0b2024; border-color: #14535b; }}
            QLabel#motionState {{ background: #1a1a15; border: 1px solid #54521b; color: {YELLOW}; font-size: 15px; font-weight: 900; letter-spacing: 1px; border-radius: 3px; }}
            QLabel#motionState[state="motion"] {{ background: #271019; border-color: #8c2341; color: {MAGENTA}; }}
            QLabel#motionState[state="offline"] {{ background: #18151b; border-color: #3b2c3d; color: #9c95a0; }}
            QComboBox {{ background: #181b22; color: {TEXT}; border: 1px solid #41434c; border-radius: 3px; padding: 6px 8px; min-height: 16px; }}
            QPushButton {{ border-radius: 3px; padding: 7px 11px; font-size: 9px; font-weight: 900; letter-spacing: .4px; }}
            QPushButton#primaryButton {{ background: {YELLOW}; color: #08090c; border: 1px solid {YELLOW}; }}
            QPushButton#primaryButton:hover {{ background: #fff85e; }}
            QPushButton#recordButton {{ background: #3b141d; color: {MAGENTA}; border: 1px solid #7a233b; }}
            QPushButton#recordButton[recording="true"] {{ background: {MAGENTA}; color: #08090c; border: 1px solid {MAGENTA}; }}
            QPushButton#secondaryButton {{ background: #1a1d24; color: #d9dbe0; border: 1px solid #464953; }}
            QPushButton#secondaryButton:hover {{ border-color: {CYAN}; color: {CYAN}; }}
            QPushButton#quietButton, QPushButton#iconButton {{ background: transparent; color: {MUTED}; border: 1px solid #383b44; }}
            QPushButton#quietButton:hover, QPushButton#iconButton:hover {{ color: {YELLOW}; border-color: {YELLOW}; }}
            QSlider::groove:horizontal {{ background: #30333b; height: 4px; border-radius: 1px; }}
            QSlider::sub-page:horizontal {{ background: {YELLOW}; }}
            QSlider::handle:horizontal {{ background: {YELLOW}; border: 2px solid #08090c; width: 12px; margin: -5px 0; border-radius: 1px; }}
            QProgressBar {{ background: #24272f; border: 0; border-radius: 2px; }}
            QProgressBar::chunk {{ background: {CYAN}; border-radius: 2px; }}
            QPlainTextEdit#logView {{ background: #0c0e12; color: #989ba6; border: 1px solid #23262f; font-family: Consolas; font-size: 9px; padding: 2px; }}
            QStatusBar {{ background: #08090c; color: #767a86; border-top: 1px solid #22252e; font-family: Consolas; font-size: 9px; }}
        """)

    # ------------------------------- Serial ----------------------------------
    def refresh_ports(self) -> None:
        current = self.port_combo.currentData()
        ports = sorted(list_ports.comports(), key=lambda item: item.device)
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        for p in ports:
            self.port_combo.addItem(f"{p.device}  /  {p.description}", p.device)
        if ports:
            selected = next((i for i, p in enumerate(ports) if p.device == current), None)
            if selected is None:
                selected = next((i for i, p in enumerate(ports) if p.device.upper() == "COM4"), 0)
            self.port_combo.setCurrentIndex(selected)
        else:
            self.port_combo.addItem("No serial ports found", None)
        self.port_combo.blockSignals(False)

    def toggle_connection(self) -> None:
        if self.serial_port and self.serial_port.is_open:
            self.disconnect_serial()
        else:
            self.connect_serial()

    def connect_serial(self) -> None:
        port_name = self.port_combo.currentData()
        if not port_name:
            QMessageBox.warning(self, "No Serial Port", "Select an available ESP32 COM port.")
            return
        try:
            while True:
                try:
                    self.inbox.get_nowait()
                except queue.Empty:
                    break
            baud = int(self.baud_combo.currentText())
            port = serial.Serial(port_name, baudrate=baud, timeout=0.03, write_timeout=0.1)
            self.serial_port = port
            self.reader = SerialReader(port, self.inbox)
            self.reader.start()
            self.connected_at = time.monotonic()
            self.connect_btn.setText("DISCONNECT  ■")
            self.port_combo.setEnabled(False)
            self.baud_combo.setEnabled(False)
            self.refresh_btn.setEnabled(False)
            self._set_connection_state("online")
            self.link_detail.setText(f"{port_name}  /  {baud} baud  ·  Streaming active")
            self._append_log(f"Serial link opened on {port_name} at {baud} baud.")
            self.statusBar().showMessage("LINK ACTIVE  /  Receiving telemetry stream")

            # Sync current detector and threshold with firmware
            self.send_firmware_command(format_command("SET_DET", 1 if self.mode_combo.currentIndex() == 0 else 0))
            self.send_firmware_command(format_command("SET_THRESH", self.trigger_threshold()))
        except Exception as exc:
            self.serial_port = None
            QMessageBox.critical(self, "Serial Open Error", f"Could not open {port_name}:\n{exc}")
            self._append_log(f"SERIAL OPEN ERROR: {exc}")

    def disconnect_serial(self) -> None:
        if self.recorder.is_recording:
            self.stop_recording()
        if self.reader:
            self.reader.stop()
        if self.serial_port:
            try:
                self.serial_port.close()
            except Exception:
                pass
        self.reader = None
        self.serial_port = None
        self.connect_btn.setText("CONNECT  ↗")
        self.port_combo.setEnabled(True)
        self.baud_combo.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self._set_connection_state("offline")
        self.motion_state.setText("OFFLINE")
        self.motion_state.setProperty("state", "offline")
        self._repolish(self.motion_state)
        self._append_log("Serial link disconnected.")

    def _set_connection_state(self, state: str) -> None:
        if state == "online":
            self.connection_badge.setText("●  LINK ACTIVE")
        else:
            self.connection_badge.setText("●  OFFLINE")
        self.connection_badge.setProperty("state", state)
        self._repolish(self.connection_badge)

    def send_firmware_command(self, cmd_str: str) -> None:
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write(cmd_str.encode("utf-8"))
            except Exception as exc:
                self._append_log(f"CMD TX ERROR: {exc}")

    # ----------------------------- Processing --------------------------------
    def trigger_threshold(self) -> int:
        return int(self.threshold_slider.value())

    def release_threshold(self) -> int:
        return max(20, int(self.trigger_threshold() * 0.65))

    def on_threshold_changed(self, value: int) -> None:
        self.threshold_value.setText(f"{value} ADC")
        self.trigger_pos.setValue(value)
        self.trigger_neg.setValue(-value)
        rel = self.release_threshold()
        self.release_pos.setValue(rel)
        self.release_neg.setValue(-rel)
        if self.serial_port and self.serial_port.is_open:
            self.send_firmware_command(format_command("SET_THRESH", value))

    def on_detector_mode_changed(self, index: int) -> None:
        mode_name = self.mode_combo.currentText()
        self._append_log(f"Active detector switched to: {mode_name}")
        if self.serial_port and self.serial_port.is_open:
            if index == 0:  # Firmware Adaptive
                self.send_firmware_command(format_command("SET_DET", 1))
            elif index == 1: # Firmware Legacy
                self.send_firmware_command(format_command("SET_DET", 0))

    def start_calibration(self) -> None:
        self.calibration_samples.clear()
        self.calibration_deadline = time.monotonic() + 2.5
        self.calibrate_btn.setEnabled(False)
        self.calibrate_btn.setText("CALIBRATING…")
        self.motion_desc.setText("Quiet calibration active — keep sensor scene still for 2.5s.")
        self._append_log("Calibration started: measuring quiet baseline & noise floor.")
        if self.serial_port and self.serial_port.is_open:
            self.send_firmware_command(format_command("CAL"))

    def finish_calibration_if_due(self, now: float) -> None:
        if self.calibration_deadline is None or now < self.calibration_deadline:
            return
        self.calibration_deadline = None
        self.calibrate_btn.setEnabled(True)
        self.calibrate_btn.setText("CALIBRATE")
        if len(self.calibration_samples) >= 8:
            noise_p80 = float(np.percentile(self.calibration_samples, 80))
            suggested = int(np.clip(round(max(60.0, noise_p80 * 2.5) / 10.0) * 10, 30, 800))
            self.threshold_slider.setValue(suggested)
            self._append_log(f"Calibration complete: quiet noise P80={noise_p80:.1f} ADC -> trigger set to {suggested} ADC.")
        else:
            self._append_log("Calibration finished.")

    def process_incoming(self) -> None:
        changed = False
        drained = 0
        now = time.monotonic()

        while drained < 1500:
            try:
                rx_time, line = self.inbox.get_nowait()
            except queue.Empty:
                break
            drained += 1

            packet = parse_telemetry_line(line, rx_time=rx_time)
            if packet is None:
                if line.startswith(("[ACK]", "[STATUS]", "===", "ADS1115", "Setup", "BOOT", "PONG")):
                    self._append_log(line[:120])
                continue

            self.cadence.update(packet)
            self.sample_count += 1
            self.latest_raw = packet.raw
            self.latest_baseline = packet.baseline
            self.latest_signal = packet.signal
            self.latest_firmware_motion = packet.firmware_motion

            # Filtered & Envelope: use extended if available, else local DSP
            if packet.filtered is not None:
                self.latest_filtered = packet.filtered
            else:
                self.latest_filtered = packet.signal

            if packet.envelope is not None:
                self.latest_envelope = packet.envelope
            else:
                # Local causal envelope update
                mag = float(abs(self.latest_filtered))
                att = 0.35 if mag > self.envelope_pc else 0.05
                self.envelope_pc = att * mag + (1.0 - att) * self.envelope_pc
                self.latest_envelope = int(round(self.envelope_pc))

            if packet.noise_floor is not None:
                self.latest_noise_floor = packet.noise_floor

            # Selected motion based on mode
            mode_idx = self.mode_combo.currentIndex()
            if mode_idx == 0:    # Firmware Adaptive
                active_motion = self.latest_firmware_motion
            elif mode_idx == 1:  # Firmware Legacy
                active_motion = self.latest_firmware_motion
            elif mode_idx == 2:  # PC Adaptive Causal
                active_motion = self.update_pc_adaptive(self.latest_envelope)
            else:                # PC Legacy Baseline
                sig_dead = 0 if abs(self.latest_signal) < 50 else self.latest_signal
                active_motion = abs(sig_dead) > self.trigger_threshold()

            self.latest_selected_motion = active_motion
            if active_motion and not self.last_selected_motion:
                self.event_count += 1
                self._append_log(f"MOTION DETECTED (Event #{self.event_count})")
            self.last_selected_motion = active_motion

            self.peak_magnitude = max(self.peak_magnitude, abs(self.latest_signal))
            self.signal_history.append(float(self.latest_filtered))
            self.motion_history.append(active_motion)

            # Record if recording active
            if self.recorder.is_recording:
                self.recorder.write_sample(packet)

            if self.calibration_deadline is not None:
                self.calibration_samples.append(float(self.latest_envelope))

            changed = True

        if changed and (now - self.last_ui_update) >= 0.033:
            self.update_metrics()
            self.last_ui_update = now

        self.finish_calibration_if_due(now)

    def update_pc_adaptive(self, envelope: int) -> bool:
        thresh = self.trigger_threshold()
        rel = self.release_threshold()
        if not self.pc_motion_active:
            if envelope >= thresh:
                self.above_count += 1
                if self.above_count >= 3:
                    self.pc_motion_active = True
                    self.above_count = 0
                    self.below_count = 0
            else:
                self.above_count = 0
        else:
            if envelope <= rel:
                self.below_count += 1
                if self.below_count >= 30:
                    self.pc_motion_active = False
                    self.above_count = 0
                    self.below_count = 0
            else:
                self.below_count = 0
        return self.pc_motion_active

    def update_metrics(self) -> None:
        self.raw_card.set_value(f"{self.latest_raw:,}", f"DC BASELINE: {self.latest_baseline:,}")
        self.signal_card.set_value(f"{self.latest_filtered:+,}", f"ENVELOPE: {self.latest_envelope:,} ADC")
        self.noise_card.set_value(f"{self.latest_noise_floor:,} ADC", f"TRIG: {self.trigger_threshold()} · REL: {self.release_threshold()}")
        diag = self.cadence.get_diagnostics()
        self.rate_card.set_value(
            f"{diag['effective_rate_hz']:.1f} Hz",
            f"DROPPED: {diag['confirmed_lost_packets']} · JITTER: {diag['timing_anomalies']}"
        )
        self.events_value.setText(f"{self.event_count:,}")
        self.peak_value.setText(f"{self.peak_magnitude:,}")
        self.envelope_readout.setText(f"{self.latest_envelope:,} ADC")
        self.signal_meter.setValue(min(1000, max(0, self.latest_envelope)))
        self.firmware_state.setText(f"FW MOTION  /  {'YES' if self.latest_firmware_motion else 'NO'}")
        self.sample_label.setText(f"{self.sample_count:,} SAMPLES")

        # Status badge
        if not (self.serial_port and self.serial_port.is_open):
            self.motion_state.setText("OFFLINE")
            self.motion_state.setProperty("state", "offline")
        elif self.latest_selected_motion:
            self.motion_state.setText("MOTION")
            self.motion_state.setProperty("state", "motion")
            self.motion_desc.setText(f"Active motion confirmed · envelope {self.latest_envelope} ADC.")
        else:
            self.motion_state.setText("SCANNING")
            self.motion_state.setProperty("state", "idle")
            self.motion_desc.setText(f"Trigger: {self.trigger_threshold()} ADC · Release: {self.release_threshold()} ADC.")
        self._repolish(self.motion_state)

    def render_plot(self) -> None:
        if self.plot_paused or not self.signal_history:
            return
        signals = np.asarray(self.signal_history, dtype=float)
        motion = np.asarray(self.motion_history, dtype=bool)
        x = np.arange(len(signals), dtype=float)

        quiet = np.where(~motion, signals, np.nan)
        moving = np.where(motion, signals, np.nan)
        self.quiet_curve.setData(x, quiet)
        self.motion_curve.setData(x, moving)

        right = max(PLOT_SAMPLES, len(signals))
        self.plot.setXRange(right - PLOT_SAMPLES if right > PLOT_SAMPLES else 0, right, padding=0)

        # Dynamic Y Range
        peak_y = float(np.percentile(np.abs(signals), 98)) if len(signals) else 50.0
        extent = min(3500.0, max(140.0, self.trigger_threshold() * 1.3, peak_y * 1.25))
        curr = self.plot.getViewBox().viewRange()[1]
        if abs(max(abs(curr[0]), abs(curr[1])) - extent) > max(20.0, extent * 0.25):
            self.plot.setYRange(-extent, extent, padding=0)

    # ---------------------------- Recording ---------------------------------
    def toggle_recording(self) -> None:
        if self.recorder.is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self) -> None:
        exp_name, ok = QInputDialog.getText(self, "New Experiment Recording", "Enter experiment label (e.g., walking_1m, hand_wave):")
        if not ok or not exp_name.strip():
            return
        cond, ok = QInputDialog.getItem(self, "Select Condition", "Select condition:", ["walking", "hand_motion", "stationary", "varying_angle", "distance_test"], 0, False)
        if not ok:
            cond = "general"

        filename = f"arguseye_{exp_name.strip().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        out_path = Path("data/experiments") / filename
        saved_path = self.recorder.start(
            output_csv_path=out_path,
            experiment_name=exp_name.strip(),
            condition=cond,
            nominal_sample_rate_hz=200.0,
        )
        self.rec_btn.setText("STOP RECORDING ■")
        self.rec_btn.setProperty("recording", "true")
        self._repolish(self.rec_btn)
        self._append_log(f"Recording started: {saved_path.name}")
        self.statusBar().showMessage(f"RECORDING ACTIVE  /  Saving to {saved_path.name}")

    def stop_recording(self) -> None:
        saved_path = self.recorder.stop()
        self.rec_btn.setText("RECORD ●")
        self.rec_btn.setProperty("recording", "false")
        self._repolish(self.rec_btn)
        if saved_path:
            self._append_log(f"Recording saved: {saved_path.name} ({self.recorder.sample_count} samples)")
            QMessageBox.information(
                self, "Recording Saved",
                f"Saved {self.recorder.sample_count:,} samples.\n\nCSV: {saved_path}\nMetadata: {saved_path.with_suffix('.meta.json')}"
            )

    # ---------------------------- Analysis ----------------------------------
    def open_spectral_analysis(self) -> None:
        if len(self.signal_history) < 32:
            QMessageBox.information(self, "Insufficient Data", "Capture live signals or load a CSV recording first.")
            return
        signals = {
            "elapsed_s": np.arange(len(self.signal_history)) * 0.005,
            "ac_signal": np.array(self.signal_history, dtype=float),
        }
        dlg = SpectralAnalysisDialog(self, signals, fs=200.0, title="Live Buffer Spectral Analysis")
        dlg.exec()

    def load_recording_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Radar Recording CSV", "data/experiments", "CSV Files (*.csv)")
        if not path:
            return
        try:
            signals, meta = load_recording(path)
            if not signals or "raw_adc" not in signals:
                QMessageBox.warning(self, "Empty Recording", "No valid samples found in the selected CSV file.")
                return

            # Run full research pipeline on loaded recording
            fs = meta.nominal_sample_rate_hz if meta else 200.0
            pipeline = RadarDSPPipeline(fs=fs)
            results = pipeline.run(signals["raw_adc"], timestamps_s=signals.get("elapsed_s"))

            # If ground truth was labeled in the CSV, compute quantitative evaluation!
            eval_text = ""
            if "ground_truth_motion" in signals and np.any(signals["ground_truth_motion"]):
                eval_legacy = evaluate_detections(
                    signals["elapsed_s"], signals["ground_truth_motion"], results["legacy_motion"], detector_name="Legacy Baseline"
                )
                eval_adaptive = evaluate_detections(
                    signals["elapsed_s"], signals["ground_truth_motion"], results["adaptive_motion"], detector_name="Adaptive Causal"
                )
                eval_text = (
                    f"\n--- EVALUATION AGAINST GROUND TRUTH ---\n"
                    f"ADAPTIVE DETECTOR: Precision={eval_adaptive.precision*100:.1f}%, "
                    f"Recall={eval_adaptive.recall*100:.1f}%, F1={eval_adaptive.f1_score*100:.1f}%, "
                    f"FAR={eval_adaptive.false_alarms_per_minute:.2f}/min, Latency={eval_adaptive.median_latency_ms:.1f}ms\n"
                    f"LEGACY DETECTOR:   Precision={eval_legacy.precision*100:.1f}%, "
                    f"Recall={eval_legacy.recall*100:.1f}%, F1={eval_legacy.f1_score*100:.1f}%, "
                    f"FAR={eval_legacy.false_alarms_per_minute:.2f}/min, Latency={eval_legacy.median_latency_ms:.1f}ms\n"
                )

            self._append_log(f"Loaded {len(signals['raw_adc']):,} samples from {Path(path).name}.{eval_text}")

            # Open Spectral View dialog for loaded file
            dlg = SpectralAnalysisDialog(self, results, fs=fs, title=f"Analysis: {Path(path).name}")
            dlg.exec()
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", f"Failed to load recording:\n{exc}")

    def toggle_plot_pause(self) -> None:
        self.plot_paused = not self.plot_paused
        if self.plot_paused:
            self.pause_btn.setText("RESUME TRACE")
            self.graph_status.setText("TRACE PAUSED")
            self._append_log("Plot display paused.")
        else:
            self.pause_btn.setText("PAUSE TRACE")
            self.graph_status.setText("LIVE TRACE · 30 FPS")
            self._append_log("Plot display resumed.")

    def clear_session(self) -> None:
        self.event_count = 0
        self.sample_count = 0
        self.peak_magnitude = 0
        self.signal_history.clear()
        self.filtered_history.clear()
        self.motion_history.clear()
        self.events_value.setText("0")
        self.peak_value.setText("0")
        self.sample_label.setText("0 SAMPLES")
        self.quiet_curve.setData([], [])
        self.motion_curve.setData([], [])
        self._append_log("Session counters and trace history cleared.")
        if self.serial_port and self.serial_port.is_open:
            self.send_firmware_command(format_command("RESET"))

    def update_session_clock(self) -> None:
        elapsed = time.monotonic() - self.session_clock_started
        hours, rem = divmod(int(elapsed), 3600)
        minutes, seconds = divmod(rem, 60)
        self.header_clock.setText(f"SESSION {hours:02d}:{minutes:02d}:{seconds:02d}")

    def _append_log(self, msg: str) -> None:
        t_str = datetime.now().strftime("%H:%M:%S")
        self.log_lines.append(f"[{t_str}]  {msg}")
        self.log_view.setPlainText("\n".join(self.log_lines))
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_view.setTextCursor(cursor)

    @staticmethod
    def _repolish(w: QWidget) -> None:
        w.style().unpolish(w)
        w.style().polish(w)
        w.update()

    def closeEvent(self, event) -> None:
        self.disconnect_serial()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))
    win = RadarDashboard()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
