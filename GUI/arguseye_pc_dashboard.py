"""ARGUS-EYE PC dashboard for ESP32 serial telemetry.

Expected firmware line format:
Raw:1234 Base:1230 Sig:4 Motion:no

Run: python arguseye_pc_dashboard.py
"""
from __future__ import annotations

import csv
import queue
import re
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np
import pyqtgraph as pg
import serial
from serial.tools import list_ports
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton, QProgressBar, QSizePolicy,
    QTextEdit, QVBoxLayout, QWidget,
)

APP_TITLE = "ARGUS-EYE // RADAR CONSOLE"
BAUD_RATE = 115200
BUFFER_SIZE = 600

# Accepts the original firmware's DEBUG_MODE line, e.g.
# Raw:12345 Base:12340 Sig:5 Motion:YES
TELEMETRY_RE = re.compile(
    r"Raw:\s*(-?\d+)\s+Base:\s*(-?\d+)\s+Sig:\s*(-?\d+)\s+Motion:\s*(YES|NO)",
    re.IGNORECASE,
)


class SerialReader(threading.Thread):
    """Read serial lines away from the GUI thread."""
    def __init__(self, port: serial.Serial, output_queue: queue.Queue):
        super().__init__(daemon=True)
        self.port = port
        self.output_queue = output_queue
        self.stop_event = threading.Event()

    def run(self):
        while not self.stop_event.is_set():
            try:
                raw = self.port.readline()
                if raw:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if line:
                        self.output_queue.put((time.time(), line))
            except (serial.SerialException, OSError) as exc:
                if not self.stop_event.is_set():
                    self.output_queue.put((time.time(), f"[SERIAL ERROR] {exc}"))
                break
            except Exception as exc:  # Keep the GUI alive if a USB adapter hiccups.
                if not self.stop_event.is_set():
                    self.output_queue.put((time.time(), f"[READ ERROR] {exc}"))
                break

    def stop(self):
        self.stop_event.set()


class MetricCard(QFrame):
    def __init__(self, eyebrow: str, initial: str = "—", accent: str = "#39f5b0"):
        super().__init__()
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(7)
        title = QLabel(eyebrow.upper())
        title.setObjectName("metricEyebrow")
        self.value = QLabel(initial)
        self.value.setObjectName("metricValue")
        self.value.setStyleSheet(f"color: {accent};")
        self.sub = QLabel("LIVE TELEMETRY")
        self.sub.setObjectName("metricSub")
        layout.addWidget(title)
        layout.addWidget(self.value)
        layout.addWidget(self.sub)

    def set_value(self, value: str, sub: str | None = None):
        self.value.setText(value)
        if sub is not None:
            self.sub.setText(sub)


class RadarDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1420, 900)
        self.setMinimumSize(1120, 740)

        self.serial_port: serial.Serial | None = None
        self.reader: SerialReader | None = None
        self.inbox: queue.Queue = queue.Queue()
        self.last_motion = False
        self.event_count = 0
        self.peak_signal = 0
        self.latest_raw = 0
        self.latest_base = 0
        self.latest_signal = 0
        self.latest_motion = False
        self.sample_count = 0
        self.started_at: float | None = None
        self.y_values = deque([0] * BUFFER_SIZE, maxlen=BUFFER_SIZE)
        self.motion_values = deque([False] * BUFFER_SIZE, maxlen=BUFFER_SIZE)
        self.csv_file = None
        self.csv_writer = None
        self.csv_path: str | None = None
        self._last_plot_update = 0.0

        self._build_ui()
        self._apply_style()
        self.refresh_ports()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_incoming)
        self.timer.start(35)

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(15)

        # Header
        header = QHBoxLayout()
        logo = QLabel("AE")
        logo.setObjectName("logo")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedSize(54, 54)
        header.addWidget(logo)
        brand_col = QVBoxLayout()
        brand_col.setSpacing(2)
        title = QLabel("ARGUS<span style='color:#39f5b0'>-EYE</span>")
        title.setObjectName("brandTitle")
        title.setTextFormat(Qt.RichText)
        subtitle = QLabel("DOPPLER RADAR  /  REAL-TIME TELEMETRY CONSOLE")
        subtitle.setObjectName("brandSubtitle")
        brand_col.addWidget(title)
        brand_col.addWidget(subtitle)
        header.addLayout(brand_col)
        header.addStretch(1)
        self.system_badge = QLabel("●  DISCONNECTED")
        self.system_badge.setObjectName("connectionBadge")
        header.addWidget(self.system_badge, alignment=Qt.AlignVCenter)
        outer.addLayout(header)

        # Connection strip
        connection = QFrame()
        connection.setObjectName("panel")
        c_layout = QHBoxLayout(connection)
        c_layout.setContentsMargins(15, 12, 15, 12)
        c_layout.setSpacing(10)
        conn_label = QLabel("SERIAL LINK")
        conn_label.setObjectName("sectionLabel")
        c_layout.addWidget(conn_label)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(260)
        self.port_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        c_layout.addWidget(self.port_combo)
        refresh_btn = QPushButton("↻  REFRESH")
        refresh_btn.setObjectName("secondaryButton")
        refresh_btn.clicked.connect(self.refresh_ports)
        c_layout.addWidget(refresh_btn)
        baud_label = QLabel("BAUD")
        baud_label.setObjectName("mutedLabel")
        c_layout.addWidget(baud_label)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200", "9600"])
        self.baud_combo.setCurrentText("115200")
        self.baud_combo.setFixedWidth(105)
        c_layout.addWidget(self.baud_combo)
        self.connect_btn = QPushButton("▶  CONNECT")
        self.connect_btn.setObjectName("primaryButton")
        self.connect_btn.clicked.connect(self.toggle_connection)
        c_layout.addWidget(self.connect_btn)
        c_layout.addStretch(1)
        self.link_detail = QLabel("Connect to the ESP32 USB serial port to begin")
        self.link_detail.setObjectName("mutedLabel")
        c_layout.addWidget(self.link_detail)
        outer.addWidget(connection)

        # Metric cards
        metrics = QGridLayout()
        metrics.setHorizontalSpacing(12)
        metrics.setVerticalSpacing(10)
        self.raw_card = MetricCard("Raw ADC", "—", "#e6edf6")
        self.base_card = MetricCard("Dynamic baseline", "—", "#9aa9bd")
        self.signal_card = MetricCard("AC signal", "—", "#39f5b0")
        self.peak_card = MetricCard("Peak amplitude", "0", "#4bc7ff")
        self.events_card = MetricCard("Motion events", "0", "#ffca6b")
        cards = [self.raw_card, self.base_card, self.signal_card, self.peak_card, self.events_card]
        for i, card in enumerate(cards):
            metrics.addWidget(card, 0, i)
        outer.addLayout(metrics)

        # Main graph + side panel
        body = QHBoxLayout()
        body.setSpacing(14)
        graph_panel = QFrame()
        graph_panel.setObjectName("panel")
        graph_layout = QVBoxLayout(graph_panel)
        graph_layout.setContentsMargins(15, 14, 15, 13)
        graph_layout.setSpacing(8)
        graph_head = QHBoxLayout()
        graph_title = QLabel("SIGNAL SCOPE")
        graph_title.setObjectName("sectionTitle")
        graph_head.addWidget(graph_title)
        graph_head.addStretch(1)
        self.sample_label = QLabel("0 SAMPLES")
        self.sample_label.setObjectName("mutedLabel")
        graph_head.addWidget(self.sample_label)
        graph_layout.addLayout(graph_head)

        pg.setConfigOptions(antialias=True)
        self.plot = pg.PlotWidget(background="#0a111a")
        self.plot.setObjectName("signalPlot")
        self.plot.showGrid(x=True, y=True, alpha=0.18)
        self.plot.setLabel("left", "AC deviation", units="ADC counts")
        self.plot.setLabel("bottom", "Recent samples")
        self.plot.setYRange(-500, 500, padding=0)
        self.plot.setXRange(0, BUFFER_SIZE - 1, padding=0)
        self.plot.getPlotItem().getAxis("left").setTextPen("#8292a6")
        self.plot.getPlotItem().getAxis("bottom").setTextPen("#8292a6")
        self.plot.getPlotItem().getAxis("left").setPen("#253447")
        self.plot.getPlotItem().getAxis("bottom").setPen("#253447")
        self.plot.getPlotItem().setMenuEnabled(False)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen("#33485a", width=1, style=Qt.DashLine)))
        self.normal_curve = self.plot.plot(pen=pg.mkPen("#39f5b0", width=2))
        self.motion_curve = self.plot.plot(pen=pg.mkPen("#ff536b", width=2.4))
        graph_layout.addWidget(self.plot, 1)
        graph_footer = QHBoxLayout()
        graph_footer.addWidget(QLabel("●  QUIET / SCANNING"))
        graph_footer.addSpacing(18)
        motion_legend = QLabel("●  MOTION EVENT")
        motion_legend.setStyleSheet("color:#ff6b80;")
        graph_footer.addWidget(motion_legend)
        graph_footer.addStretch(1)
        hint = QLabel("Streaming from ESP32 · 115200 baud recommended")
        hint.setObjectName("mutedLabel")
        graph_footer.addWidget(hint)
        graph_layout.addLayout(graph_footer)
        body.addWidget(graph_panel, 3)

        side = QVBoxLayout()
        side.setSpacing(14)
        status_panel = QFrame()
        status_panel.setObjectName("panel")
        status_layout = QVBoxLayout(status_panel)
        status_layout.setContentsMargins(18, 18, 18, 18)
        status_layout.setSpacing(12)
        status_head = QLabel("DETECTION STATUS")
        status_head.setObjectName("sectionLabel")
        status_layout.addWidget(status_head)
        self.motion_state = QLabel("WAITING FOR DATA")
        self.motion_state.setObjectName("motionState")
        self.motion_state.setAlignment(Qt.AlignCenter)
        self.motion_state.setMinimumHeight(82)
        status_layout.addWidget(self.motion_state)
        self.motion_desc = QLabel("Connect your ESP32 to start monitoring movement.")
        self.motion_desc.setObjectName("mutedLabel")
        self.motion_desc.setWordWrap(True)
        status_layout.addWidget(self.motion_desc)
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setObjectName("divider")
        status_layout.addWidget(divider)
        meter_top = QHBoxLayout()
        meter_title = QLabel("SIGNAL MAGNITUDE")
        meter_title.setObjectName("sectionLabel")
        self.meter_value = QLabel("0 / 500")
        self.meter_value.setObjectName("meterValue")
        meter_top.addWidget(meter_title)
        meter_top.addStretch(1)
        meter_top.addWidget(self.meter_value)
        status_layout.addLayout(meter_top)
        self.signal_meter = QProgressBar()
        self.signal_meter.setRange(0, 500)
        self.signal_meter.setValue(0)
        self.signal_meter.setTextVisible(False)
        self.signal_meter.setFixedHeight(13)
        status_layout.addWidget(self.signal_meter)
        small_note = QLabel("Magnitude is the absolute value of the filtered AC signal. Motion uses the firmware threshold.")
        small_note.setObjectName("smallNote")
        small_note.setWordWrap(True)
        status_layout.addWidget(small_note)
        side.addWidget(status_panel, 1)

        actions_panel = QFrame()
        actions_panel.setObjectName("panel")
        actions_layout = QVBoxLayout(actions_panel)
        actions_layout.setContentsMargins(18, 16, 18, 16)
        actions_layout.setSpacing(10)
        actions_title = QLabel("SESSION TOOLS")
        actions_title.setObjectName("sectionLabel")
        actions_layout.addWidget(actions_title)
        self.export_btn = QPushButton("⇩  EXPORT SESSION CSV")
        self.export_btn.setObjectName("secondaryButton")
        self.export_btn.clicked.connect(self.export_csv)
        self.export_btn.setEnabled(False)
        actions_layout.addWidget(self.export_btn)
        self.clear_btn = QPushButton("⌫  CLEAR SESSION COUNTERS")
        self.clear_btn.setObjectName("secondaryButton")
        self.clear_btn.clicked.connect(self.clear_session)
        actions_layout.addWidget(self.clear_btn)
        self.session_time = QLabel("SESSION DURATION   00:00:00")
        self.session_time.setObjectName("mutedLabel")
        actions_layout.addWidget(self.session_time)
        self.firmware_hint = QLabel("FIRMWARE INPUT\nRaw / Base / Sig / Motion")
        self.firmware_hint.setObjectName("smallNote")
        actions_layout.addWidget(self.firmware_hint)
        side.addWidget(actions_panel)
        body.addLayout(side, 1)
        outer.addLayout(body, 1)

        # Compact serial feed
        log_panel = QFrame()
        log_panel.setObjectName("panel")
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(14, 10, 14, 10)
        log_layout.setSpacing(6)
        log_head = QHBoxLayout()
        feed_title = QLabel("SERIAL FEED")
        feed_title.setObjectName("sectionLabel")
        log_head.addWidget(feed_title)
        log_head.addStretch(1)
        self.feed_state = QLabel("READY")
        self.feed_state.setObjectName("mutedLabel")
        log_head.addWidget(self.feed_state)
        log_layout.addLayout(log_head)
        self.log_view = QTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QTextEdit.NoWrap)
        self.log_view.setFixedHeight(105)
        self.log_view.setPlaceholderText("Serial diagnostics and incoming telemetry will appear here…")
        log_layout.addWidget(self.log_view)
        outer.addWidget(log_panel)

        self.statusBar().showMessage("Ready · Restore your original radar firmware to stream live samples")

    def _apply_style(self):
        self.setStyleSheet("""
            QWidget#root { background:#070c12; color:#e7eef7; font-family:'Segoe UI'; font-size:12px; }
            QLabel { color:#e7eef7; }
            QLabel#logo { background:#10251f; border:1px solid #24694f; border-radius:14px; color:#39f5b0; font-size:20px; font-weight:800; }
            QLabel#brandTitle { color:#f2f7fc; font-size:25px; font-weight:800; letter-spacing:1px; }
            QLabel#brandSubtitle { color:#8292a6; font-size:10px; letter-spacing:2px; }
            QFrame#panel, QFrame#metricCard { background:#0d151f; border:1px solid #1b2a3a; border-radius:14px; }
            QLabel#metricEyebrow, QLabel#sectionLabel { color:#8fa0b5; font-size:10px; font-weight:700; letter-spacing:1.4px; }
            QLabel#metricValue { font-size:25px; font-weight:750; }
            QLabel#metricSub { color:#63778d; font-size:9px; letter-spacing:1px; }
            QLabel#sectionTitle { color:#eef5fc; font-size:14px; font-weight:750; letter-spacing:1px; }
            QLabel#mutedLabel { color:#74879d; font-size:10px; }
            QLabel#smallNote { color:#71849a; font-size:10px; }
            QLabel#connectionBadge { color:#ffca6b; background:#2b2417; border:1px solid #5e4926; padding:8px 12px; border-radius:10px; font-size:10px; font-weight:700; }
            QComboBox { background:#111d29; border:1px solid #293c50; border-radius:8px; padding:8px 10px; color:#e7eef7; min-height:18px; }
            QComboBox QAbstractItemView { background:#101a26; selection-background-color:#1b513d; color:#e7eef7; }
            QPushButton { border-radius:8px; padding:10px 13px; font-weight:700; font-size:10px; letter-spacing:.4px; }
            QPushButton#primaryButton { background:#39f5b0; color:#062016; border:1px solid #39f5b0; }
            QPushButton#primaryButton:hover { background:#6fffc8; }
            QPushButton#secondaryButton { background:#142230; color:#c9d6e5; border:1px solid #293c50; }
            QPushButton#secondaryButton:hover { background:#1a3040; border-color:#42617b; }
            QPushButton:disabled { color:#536577; background:#101720; border-color:#202d3a; }
            QLabel#motionState { background:#17251f; color:#39f5b0; border:1px solid #285b45; border-radius:11px; font-size:18px; font-weight:800; letter-spacing:1.5px; }
            QLabel#motionState[motion="true"] { background:#321820; color:#ff667a; border:1px solid #773140; }
            QLabel#meterValue { color:#39f5b0; font-size:12px; font-weight:700; }
            QProgressBar { background:#172331; border:1px solid #263749; border-radius:6px; }
            QProgressBar::chunk { background:#39f5b0; border-radius:5px; }
            QFrame#divider { color:#1c2a38; max-height:1px; }
            QTextEdit#logView { background:#080e15; border:1px solid #172331; border-radius:8px; color:#86a1b9; font-family:Consolas; font-size:10px; padding:6px; }
            QStatusBar { background:#080e15; color:#71849a; border-top:1px solid #172331; }
        """)

    def refresh_ports(self):
        current = self.port_combo.currentData()
        self.port_combo.clear()
        ports = sorted(list_ports.comports(), key=lambda p: p.device)
        for p in ports:
            self.port_combo.addItem(f"{p.device}  —  {p.description}", p.device)
        if ports:
            preferred = next((i for i, p in enumerate(ports) if p.device == current), None)
            if preferred is None:
                preferred = next((i for i, p in enumerate(ports) if p.device.upper() == "COM4"), 0)
            self.port_combo.setCurrentIndex(preferred)
        else:
            self.port_combo.addItem("No serial ports found", None)
        self._append_log(f"Detected {len(ports)} serial port(s).")

    def toggle_connection(self):
        if self.serial_port and self.serial_port.is_open:
            self.disconnect_serial()
        else:
            self.connect_serial()

    def connect_serial(self):
        port_name = self.port_combo.currentData()
        if not port_name:
            QMessageBox.warning(self, "No serial port", "No serial port was found. Connect the ESP32 and click REFRESH.")
            return
        try:
            baud = int(self.baud_combo.currentText())
            self.serial_port = serial.Serial(port_name, baudrate=baud, timeout=0.12)
            # Many ESP32-S3 boards reset when the serial port is opened.
            time.sleep(0.15)
            self.reader = SerialReader(self.serial_port, self.inbox)
            self.reader.start()
            self.started_at = time.time()
            self.connect_btn.setText("■  DISCONNECT")
            self.system_badge.setText("●  LINK OPEN · WAITING")
            self.system_badge.setStyleSheet("color:#39f5b0; background:#10271f; border:1px solid #285b45; padding:8px 12px; border-radius:10px; font-size:10px; font-weight:700;")
            self.link_detail.setText(f"{port_name} · {baud} baud")
            self.feed_state.setText("PORT OPEN")
            self._append_log(f"Opened {port_name} at {baud} baud. Close PlatformIO Serial Monitor if it is open.")
            self.statusBar().showMessage("Connected · waiting for telemetry matching Raw / Base / Sig / Motion")
        except (serial.SerialException, OSError, ValueError) as exc:
            self.serial_port = None
            QMessageBox.critical(self, "Could not open serial port", f"Could not open {port_name}.\n\n{exc}\n\nClose PlatformIO's Serial Monitor and try again.")
            self._append_log(f"ERROR opening {port_name}: {exc}")

    def disconnect_serial(self):
        if self.reader:
            self.reader.stop()
        if self.serial_port:
            try:
                if self.serial_port.is_open:
                    self.serial_port.close()
            except Exception:
                pass
        if self.reader:
            self.reader.join(timeout=0.3)
        self.reader = None
        self.serial_port = None
        self.connect_btn.setText("▶  CONNECT")
        self.system_badge.setText("●  DISCONNECTED")
        self.system_badge.setStyleSheet("")
        self.link_detail.setText("Connect to the ESP32 USB serial port to begin")
        self.feed_state.setText("DISCONNECTED")
        self.motion_state.setText("LINK OFFLINE")
        self.motion_state.setProperty("motion", False)
        self.motion_state.style().unpolish(self.motion_state)
        self.motion_state.style().polish(self.motion_state)
        self.motion_desc.setText("Serial connection closed.")
        self._append_log("Serial link closed.")

    def process_incoming(self):
        drained = 0
        plot_dirty = False
        while drained < 900:
            try:
                stamp, line = self.inbox.get_nowait()
            except queue.Empty:
                break
            drained += 1
            match = TELEMETRY_RE.search(line)
            if not match:
                # Show useful firmware/banner lines and errors, but avoid flooding UI with duplicates.
                if line.startswith("[") or "BOOT" in line or "ADS1115" in line or "ERROR" in line or "Starting" in line or "Setup" in line:
                    self._append_log(line)
                continue

            raw = int(match.group(1))
            base = int(match.group(2))
            signal = int(match.group(3))
            motion = match.group(4).upper() == "YES"
            self.latest_raw = raw
            self.latest_base = base
            self.latest_signal = signal
            self.latest_motion = motion
            self.sample_count += 1
            self.peak_signal = max(self.peak_signal, abs(signal))
            if motion and not self.last_motion:
                self.event_count += 1
                self._append_log(f"MOTION EDGE DETECTED · event #{self.event_count}")
            self.last_motion = motion
            self.y_values.append(signal)
            self.motion_values.append(motion)
            plot_dirty = True

        if plot_dirty:
            self.update_dashboard()
        if self.started_at is not None:
            elapsed = int(time.time() - self.started_at)
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            self.session_time.setText(f"SESSION DURATION   {h:02d}:{m:02d}:{s:02d}")

    def update_dashboard(self):
        self.raw_card.set_value(f"{self.latest_raw:,}", "LATEST ADC SAMPLE")
        self.base_card.set_value(f"{self.latest_base:,}", "LOW-PASS BASELINE")
        self.signal_card.set_value(f"{self.latest_signal:+,}", "FILTERED AC SIGNAL")
        self.peak_card.set_value(f"{self.peak_signal:,}", "SESSION PEAK · ABS")
        self.events_card.set_value(f"{self.event_count:,}", "RISING-EDGE COUNT")
        magnitude = min(abs(self.latest_signal), 500)
        self.signal_meter.setValue(magnitude)
        self.meter_value.setText(f"{abs(self.latest_signal)} / 500")
        if self.latest_motion:
            self.motion_state.setText("MOTION DETECTED")
            self.motion_state.setProperty("motion", True)
            self.motion_desc.setText("The ESP32 reports that signal magnitude is above its configured motion threshold.")
            self.system_badge.setText("●  LINK ACTIVE · MOTION")
        else:
            self.motion_state.setText("SCANNING")
            self.motion_state.setProperty("motion", False)
            self.motion_desc.setText("Radar is streaming. No motion event is currently asserted by the firmware.")
            self.system_badge.setText("●  LINK ACTIVE · SCANNING")
        self.motion_state.style().unpolish(self.motion_state)
        self.motion_state.style().polish(self.motion_state)
        y = np.asarray(self.y_values, dtype=float)
        moving = np.asarray(self.motion_values, dtype=bool)
        x = np.arange(len(y))
        self.normal_curve.setData(x, np.where(~moving, y, np.nan))
        self.motion_curve.setData(x, np.where(moving, y, np.nan))
        self.sample_label.setText(f"{self.sample_count:,} SAMPLES")
        self.export_btn.setEnabled(self.sample_count > 0)
        self.feed_state.setText("LIVE · TELEMETRY PARSED")
        self.statusBar().showMessage("Streaming telemetry · close the dashboard before using PlatformIO Serial Monitor")

    def export_csv(self):
        if self.sample_count == 0:
            QMessageBox.information(self, "No data yet", "Connect the ESP32 and wait for telemetry before exporting.")
            return
        default_name = f"arguseye_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export current visible trace", str(Path.home() / default_name), "CSV files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["sample_index", "signal", "motion"])
                start_idx = max(0, self.sample_count - len(self.y_values))
                for idx, (sig, moving) in enumerate(zip(self.y_values, self.motion_values), start=start_idx):
                    writer.writerow([idx, sig, int(moving)])
            self._append_log(f"Exported visible trace to {path}")
            QMessageBox.information(self, "CSV exported", f"Saved recent plotted samples to:\n{path}\n\nNote: this exports the current graph buffer ({len(self.y_values)} samples), not the entire session history.")
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def clear_session(self):
        self.event_count = 0
        self.peak_signal = abs(self.latest_signal)
        self.sample_count = 0
        self.y_values = deque([0] * BUFFER_SIZE, maxlen=BUFFER_SIZE)
        self.motion_values = deque([False] * BUFFER_SIZE, maxlen=BUFFER_SIZE)
        self.normal_curve.setData(np.arange(BUFFER_SIZE), np.zeros(BUFFER_SIZE))
        self.motion_curve.setData(np.arange(BUFFER_SIZE), np.full(BUFFER_SIZE, np.nan))
        self.events_card.set_value("0", "RISING-EDGE COUNT")
        self.peak_card.set_value(f"{self.peak_signal:,}", "SESSION PEAK · ABS")
        self.sample_label.setText("0 SAMPLES")
        self.export_btn.setEnabled(False)
        self._append_log("Session counters and graph buffer cleared.")

    def _append_log(self, text: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.append(f"<span style='color:#50667d'>[{timestamp}]</span> {text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')}")
        # Keep the widget lightweight for extended sessions.
        doc = self.log_view.document()
        if doc.blockCount() > 140:
            cursor = self.log_view.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.select(cursor.LineUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

    def closeEvent(self, event):
        self.disconnect_serial()
        if self.csv_file:
            try:
                self.csv_file.close()
            except Exception:
                pass
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    window = RadarDashboard()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
