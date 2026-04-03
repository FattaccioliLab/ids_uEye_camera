"""
main_window.py — PyQt6 GUI for the IDS uEye camera acquisition software.
Live preview runs in a dedicated QThread to keep the UI responsive.
"""

import threading
from pathlib import Path

import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QPushButton, QSlider, QSpinBox,
    QDoubleSpinBox, QGroupBox, QVBoxLayout, QHBoxLayout, QGridLayout,
    QCheckBox, QComboBox, QFileDialog, QStatusBar, QProgressBar,
    QLineEdit, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage, QPixmap, QFont

from ids_camera import IDSCamera
from processing import ProcessingPipeline
import acquisition as acq


# ---------------------------------------------------------------------------
# Live preview worker
# ---------------------------------------------------------------------------

class PreviewWorker(QThread):
    frame_ready = pyqtSignal(np.ndarray)
    error       = pyqtSignal(str)

    def __init__(self, camera: IDSCamera):
        super().__init__()
        self._camera  = camera
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            try:
                frame = self._camera.grab_frame(timeout_ms=2000)
                self.frame_ready.emit(frame)
            except Exception as e:
                self.error.emit(str(e))
                break

    def stop(self):
        self._running = False
        self.wait()


# ---------------------------------------------------------------------------
# Acquisition worker
# ---------------------------------------------------------------------------

class AcquisitionWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(int)
    error    = pyqtSignal(str)

    def __init__(self, camera, mode, params):
        super().__init__()
        self._camera    = camera
        self._mode      = mode
        self._params    = params
        self._stop_flag = threading.Event()

    def run(self):
        try:
            p = self._params
            if self._mode == "single":
                acq.grab_single(self._camera, p["save_dir"], p["prefix"])
                self.finished.emit(1)
            elif self._mode == "timelapse":
                paths = acq.run_timelapse(
                    self._camera, p["save_dir"], p["n_frames"], p["interval_s"],
                    p["prefix"], self._emit_progress, self._stop_flag)
                self.finished.emit(len(paths))
            elif self._mode == "burst":
                paths = acq.run_burst(
                    self._camera, p["save_dir"], p["n_frames"],
                    p["prefix"], self._emit_progress, self._stop_flag)
                self.finished.emit(len(paths))
        except Exception as e:
            self.error.emit(str(e))

    def _emit_progress(self, current, total):
        self.progress.emit(current, total)

    def stop(self):
        self._stop_flag.set()
        self.wait()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IDS Camera Acquisition")
        self.setMinimumSize(1200, 780)

        self._camera         = IDSCamera()
        self._pipeline       = ProcessingPipeline()
        self._preview_worker = None
        self._acq_worker     = None
        self._previewing     = False

        self._build_ui()
        self._connect_camera()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setSpacing(10)
        root.setContentsMargins(10, 10, 10, 10)

        # ---- Left: preview ----
        left = QVBoxLayout()
        self._preview_label = QLabel("No preview")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumSize(640, 512)
        self._preview_label.setSizePolicy(QSizePolicy.Policy.Expanding,
                                          QSizePolicy.Policy.Expanding)
        self._preview_label.setStyleSheet("background: #1a1a1a; color: #666;")
        left.addWidget(self._preview_label)

        self._stats_label = QLabel("")
        self._stats_label.setFont(QFont("Monospace", 9))
        left.addWidget(self._stats_label)
        root.addLayout(left, stretch=3)

        # ---- Right: controls ----
        right = QVBoxLayout()
        right.setSpacing(8)
        right.addWidget(self._build_camera_controls())
        right.addWidget(self._build_roi_controls())
        right.addWidget(self._build_processing_controls())
        right.addWidget(self._build_acquisition_controls())
        right.addStretch()

        btn_quit = QPushButton("⏏  Stop stream & Quit")
        btn_quit.setStyleSheet(
            "QPushButton { color: #c0392b; font-weight: bold; padding: 6px; }"
        )
        btn_quit.clicked.connect(self._quit)
        right.addWidget(btn_quit)

        root.addLayout(right, stretch=1)

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setMaximumWidth(200)
        self._status.addPermanentWidget(self._progress)
        self._status.showMessage("Ready")

    def _build_camera_controls(self):
        gb = QGroupBox("Camera")
        layout = QGridLayout(gb)

        self._btn_preview = QPushButton("▶  Start Preview")
        self._btn_preview.setCheckable(True)
        self._btn_preview.clicked.connect(self._toggle_preview)
        layout.addWidget(self._btn_preview, 0, 0, 1, 2)

        layout.addWidget(QLabel("Exposure (µs)"), 1, 0)
        self._exp_spin = QDoubleSpinBox()
        self._exp_spin.setDecimals(1)
        self._exp_spin.setSingleStep(100)
        self._exp_spin.editingFinished.connect(self._set_exposure)
        layout.addWidget(self._exp_spin, 1, 1)

        self._exp_slider = QSlider(Qt.Orientation.Horizontal)
        self._exp_slider.setMinimum(1)
        self._exp_slider.setMaximum(1000)
        self._exp_slider.sliderMoved.connect(self._slider_to_exposure)
        layout.addWidget(self._exp_slider, 2, 0, 1, 2)

        layout.addWidget(QLabel("Gain"), 3, 0)
        self._gain_spin = QDoubleSpinBox()
        self._gain_spin.setDecimals(2)
        self._gain_spin.setSingleStep(0.1)
        self._gain_spin.editingFinished.connect(self._set_gain)
        layout.addWidget(self._gain_spin, 3, 1)

        return gb

    def _build_roi_controls(self):
        gb = QGroupBox("ROI (hardware)")
        layout = QGridLayout(gb)

        for i, label in enumerate(["X", "Y", "Width", "Height"]):
            layout.addWidget(QLabel(label), i, 0)

        self._roi_x = QSpinBox(); self._roi_x.setMaximum(9999)
        self._roi_y = QSpinBox(); self._roi_y.setMaximum(9999)
        self._roi_w = QSpinBox(); self._roi_w.setMaximum(9999)
        self._roi_h = QSpinBox(); self._roi_h.setMaximum(9999)

        for i, sp in enumerate([self._roi_x, self._roi_y,
                                 self._roi_w, self._roi_h]):
            layout.addWidget(sp, i, 1)

        btn_apply = QPushButton("Apply ROI")
        btn_apply.clicked.connect(self._apply_roi)
        btn_full  = QPushButton("Full sensor")
        btn_full.clicked.connect(self._reset_roi)
        layout.addWidget(btn_apply, 4, 0)
        layout.addWidget(btn_full,  4, 1)

        return gb

    def _build_processing_controls(self):
        gb = QGroupBox("Processing (preview only)")
        layout = QVBoxLayout(gb)

        self._chk_threshold = QCheckBox("Threshold / Binarize")
        self._chk_threshold.toggled.connect(self._toggle_threshold)
        layout.addWidget(self._chk_threshold)

        row = QHBoxLayout()
        row.addWidget(QLabel("Value"))
        self._thr_spin = QSpinBox()
        self._thr_spin.setRange(0, 255)
        self._thr_spin.setValue(128)
        self._thr_spin.valueChanged.connect(self._set_threshold_value)
        row.addWidget(self._thr_spin)

        self._thr_mode = QComboBox()
        self._thr_mode.addItems(["Binary", "Otsu"])
        self._thr_mode.currentTextChanged.connect(self._set_threshold_mode)
        row.addWidget(self._thr_mode)
        layout.addLayout(row)

        return gb

    def _build_acquisition_controls(self):
        gb = QGroupBox("Acquisition")
        layout = QGridLayout(gb)

        layout.addWidget(QLabel("Save dir"), 0, 0)
        self._save_dir = QLineEdit(str(Path.home() / "camera_data"))
        layout.addWidget(self._save_dir, 0, 1)
        btn_browse = QPushButton("…")
        btn_browse.setMaximumWidth(30)
        btn_browse.clicked.connect(self._browse_save_dir)
        layout.addWidget(btn_browse, 0, 2)

        layout.addWidget(QLabel("Prefix"), 1, 0)
        self._prefix = QLineEdit("frame")
        layout.addWidget(self._prefix, 1, 1, 1, 2)

        layout.addWidget(QLabel("Mode"), 2, 0)
        self._acq_mode = QComboBox()
        self._acq_mode.addItems(["Single", "Timelapse", "Burst"])
        self._acq_mode.currentTextChanged.connect(self._update_acq_mode_ui)
        layout.addWidget(self._acq_mode, 2, 1, 1, 2)

        layout.addWidget(QLabel("N frames"), 3, 0)
        self._n_frames = QSpinBox()
        self._n_frames.setRange(1, 100000)
        self._n_frames.setValue(10)
        layout.addWidget(self._n_frames, 3, 1, 1, 2)

        self._lbl_interval = QLabel("Interval (s)")
        layout.addWidget(self._lbl_interval, 4, 0)
        self._interval = QDoubleSpinBox()
        self._interval.setRange(0.0, 3600.0)
        self._interval.setValue(1.0)
        self._interval.setDecimals(2)
        layout.addWidget(self._interval, 4, 1, 1, 2)

        self._btn_acquire = QPushButton("⏺  Acquire")
        self._btn_acquire.clicked.connect(self._start_acquisition)
        self._btn_stop_acq = QPushButton("⏹  Stop")
        self._btn_stop_acq.setEnabled(False)
        self._btn_stop_acq.clicked.connect(self._stop_acquisition)
        layout.addWidget(self._btn_acquire,  5, 0, 1, 2)
        layout.addWidget(self._btn_stop_acq, 5, 2)

        self._update_acq_mode_ui("Single")
        return gb

    # ------------------------------------------------------------------
    # Camera init
    # ------------------------------------------------------------------

    def _connect_camera(self):
        try:
            self._camera.open()
            info = self._camera.info()
            self.setWindowTitle(
                f"IDS Acquisition — {info['model']} [{info['serial']}]"
            )
            self._status.showMessage(
                f"Connected: {info['model']} | {info['width']}x{info['height']} px"
            )
            self._init_parameter_widgets()
        except Exception as e:
            self._status.showMessage(f"Camera error: {e}")

    def _init_parameter_widgets(self):
        exp_min, exp_max = self._camera.get_exposure_range()
        self._exp_spin.setRange(exp_min, exp_max)
        self._exp_spin.setValue(self._camera.get_exposure())

        gain_min, gain_max = self._camera.get_gain_range()
        self._gain_spin.setRange(gain_min, gain_max)
        self._gain_spin.setValue(self._camera.get_gain())

        roi = self._camera.get_roi()
        w_max, h_max = self._camera.get_sensor_size()
        for sp in [self._roi_x, self._roi_y, self._roi_w, self._roi_h]:
            sp.setMaximum(max(w_max, h_max))
        self._roi_x.setValue(roi["x"])
        self._roi_y.setValue(roi["y"])
        self._roi_w.setValue(roi["width"])
        self._roi_h.setValue(roi["height"])

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _toggle_preview(self):
        if self._btn_preview.isChecked():
            self._start_preview()
        else:
            self._stop_preview()

    def _start_preview(self):
        self._camera.start_stream()
        self._preview_worker = PreviewWorker(self._camera)
        self._preview_worker.frame_ready.connect(self._on_frame)
        self._preview_worker.error.connect(self._on_preview_error)
        self._preview_worker.start()
        self._btn_preview.setText("⏹  Stop Preview")
        self._previewing = True

    def _stop_preview(self):
        if self._preview_worker:
            self._preview_worker.stop()
            self._preview_worker = None
        self._camera.stop_stream()
        self._btn_preview.setText("▶  Start Preview")
        self._btn_preview.setChecked(False)
        self._previewing = False

    @pyqtSlot(np.ndarray)
    def _on_frame(self, frame: np.ndarray):
        display = self._pipeline.process(frame)

        mean = display.mean()
        pmin, pmax = int(display.min()), int(display.max())
        self._stats_label.setText(
            f"min={pmin}  max={pmax}  mean={mean:.1f}  "
            f"{display.shape[1]}x{display.shape[0]}"
        )

        h, w = display.shape[:2]
        if display.ndim == 2:
            qimg = QImage(display.data, w, h, w,
                          QImage.Format.Format_Grayscale8)
        else:
            qimg = QImage(display.data, w, h, 3 * w,
                          QImage.Format.Format_RGB888)

        pixmap = QPixmap.fromImage(qimg).scaled(
            self._preview_label.width(),
            self._preview_label.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self._preview_label.setPixmap(pixmap)

    @pyqtSlot(str)
    def _on_preview_error(self, msg: str):
        self._status.showMessage(f"Preview error: {msg}")
        self._stop_preview()

    # ------------------------------------------------------------------
    # Camera parameter handlers
    # ------------------------------------------------------------------

    def _set_exposure(self):
        try:
            self._camera.set_exposure(self._exp_spin.value())
        except Exception as e:
            self._status.showMessage(f"Exposure error: {e}")

    def _slider_to_exposure(self, slider_val: int):
        import math
        exp_min, exp_max = self._camera.get_exposure_range()
        log_min = math.log10(max(exp_min, 1))
        log_max = math.log10(exp_max)
        value = 10 ** (log_min + (slider_val - 1) / 999 * (log_max - log_min))
        self._exp_spin.setValue(value)
        self._camera.set_exposure(value)

    def _set_gain(self):
        try:
            self._camera.set_gain(self._gain_spin.value())
        except Exception as e:
            self._status.showMessage(f"Gain error: {e}")

    # ------------------------------------------------------------------
    # ROI
    # ------------------------------------------------------------------

    def _apply_roi(self):
        try:
            self._camera.set_roi(
                self._roi_x.value(), self._roi_y.value(),
                self._roi_w.value(), self._roi_h.value()
            )
            roi = self._camera.get_roi()
            self._status.showMessage(
                f"ROI set: {roi['width']}x{roi['height']} "
                f"@ ({roi['x']},{roi['y']})"
            )
        except Exception as e:
            self._status.showMessage(f"ROI error: {e}")

    def _reset_roi(self):
        w_max, h_max = self._camera.get_sensor_size()
        self._roi_x.setValue(0)
        self._roi_y.setValue(0)
        self._roi_w.setValue(w_max)
        self._roi_h.setValue(h_max)
        self._apply_roi()

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def _toggle_threshold(self, state: bool):
        self._pipeline.threshold_enabled = state

    def _set_threshold_value(self, val: int):
        self._pipeline.threshold_value = val

    def _set_threshold_mode(self, mode: str):
        self._pipeline.threshold_mode = mode.lower()
        self._thr_spin.setEnabled(mode.lower() != "otsu")

    # ------------------------------------------------------------------
    # Acquisition
    # ------------------------------------------------------------------

    def _update_acq_mode_ui(self, mode: str):
        is_single = (mode == "Single")
        self._n_frames.setEnabled(not is_single)
        self._lbl_interval.setEnabled(mode == "Timelapse")
        self._interval.setEnabled(mode == "Timelapse")

    def _browse_save_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "Select save directory", self._save_dir.text()
        )
        if d:
            self._save_dir.setText(d)

    def _start_acquisition(self):
        mode = self._acq_mode.currentText().lower()
        params = {
            "save_dir":   self._save_dir.text(),
            "prefix":     self._prefix.text() or "frame",
            "n_frames":   self._n_frames.value(),
            "interval_s": self._interval.value(),
        }
        if not self._previewing:
            self._camera.start_stream()

        self._acq_worker = AcquisitionWorker(self._camera, mode, params)
        self._acq_worker.progress.connect(self._on_acq_progress)
        self._acq_worker.finished.connect(self._on_acq_finished)
        self._acq_worker.error.connect(self._on_acq_error)
        self._acq_worker.start()

        self._btn_acquire.setEnabled(False)
        self._btn_stop_acq.setEnabled(True)
        self._progress.setVisible(True)
        self._progress.setRange(0, params["n_frames"] if mode != "single" else 1)
        self._progress.setValue(0)
        self._status.showMessage(f"Acquiring ({mode})...")

    def _stop_acquisition(self):
        if self._acq_worker:
            self._acq_worker.stop()

    @pyqtSlot(int, int)
    def _on_acq_progress(self, current: int, total: int):
        self._progress.setMaximum(total)
        self._progress.setValue(current)
        self._status.showMessage(f"Acquired {current}/{total} frames...")

    @pyqtSlot(int)
    def _on_acq_finished(self, n: int):
        self._btn_acquire.setEnabled(True)
        self._btn_stop_acq.setEnabled(False)
        self._progress.setVisible(False)
        self._status.showMessage(
            f"Done - {n} frame(s) saved to {self._save_dir.text()}"
        )
        if not self._previewing:
            self._camera.stop_stream()

    @pyqtSlot(str)
    def _on_acq_error(self, msg: str):
        self._status.showMessage(f"Acquisition error: {msg}")
        self._btn_acquire.setEnabled(True)
        self._btn_stop_acq.setEnabled(False)
        self._progress.setVisible(False)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _quit(self):
        self._cleanup()
        self.close()

    def _cleanup(self):
        self._status.showMessage("Stopping stream and closing camera...")
        if self._preview_worker:
            self._preview_worker.stop()
            self._preview_worker = None
        if self._acq_worker and self._acq_worker.isRunning():
            self._acq_worker.stop()
            self._acq_worker = None
        try:
            self._camera.stop_stream()
            self._camera.close()
        except Exception as e:
            print(f"Camera close error: {e}")

    def closeEvent(self, event):
        self._cleanup()
        event.accept()
