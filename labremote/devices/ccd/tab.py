"""Local CCD panel. The GUI never reads the SDK or waits on an operation."""
import time
from datetime import datetime
from pathlib import Path
from PyQt5 import QtCore, QtWidgets
import pyqtgraph as pg
from .worker import CCDWorker, CCDAPI


class CCDViewBox(pg.ViewBox):
    """Wheel zoom, left-button pan, middle-button rectangle zoom."""
    def mouseDragEvent(self, event, axis=None):
        if event.button() != QtCore.Qt.MiddleButton or axis is not None:
            return super().mouseDragEvent(event, axis=axis)
        event.accept()
        start = event.buttonDownPos(QtCore.Qt.MiddleButton)
        end = event.pos()
        if event.isFinish():
            self.rbScaleBox.hide()
            rectangle = QtCore.QRectF(start, end).normalized()
            if rectangle.width() >= 4 and rectangle.height() >= 4:
                self.showAxRect(self.childGroup.mapRectFromParent(rectangle))
                self.sigRangeChangedManually.emit(self.state['mouseEnabled'])
        else:
            self.updateScaleBox(start, end)


class CCDTab(QtWidgets.QWidget):
    log_message = QtCore.pyqtSignal(str)

    def __init__(self, parent=None, options=None):
        super().__init__(parent)
        self.options = dict(options or {})
        self.worker = CCDWorker()
        self.api = CCDAPI(self.worker)
        self._last_frame = None
        self._redraw = True
        self._watch = None
        self.worker.connected.connect(self._connected)
        self.worker.disconnected.connect(self._disconnected)
        self.worker.failure.connect(lambda action, error: self.log_message.emit(f'{action}: {error}'))
        self.worker.handle_changed.connect(self._completed)
        self.worker.state_changed.connect(self._state)
        self.worker.start()
        layout = QtWidgets.QVBoxLayout(self)
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setMinimumHeight(620)
        self.splitter.setMaximumHeight(780)
        layout.addWidget(self.splitter)
        image_panel = QtWidgets.QWidget()
        image_layout = QtWidgets.QVBoxLayout(image_panel)
        image_layout.setContentsMargins(0, 0, 8, 0)
        hint = QtWidgets.QLabel('휠: 확대/축소 · 휠 버튼 드래그: 영역 확대 · 왼쪽 드래그: 이동')
        hint.setWordWrap(True)
        image_layout.addWidget(hint)
        self.splitter.addWidget(image_panel)
        self.controls_scroll = QtWidgets.QScrollArea()
        self.controls_scroll.setWidgetResizable(True)
        self.controls_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.controls_scroll.setMinimumWidth(390)
        control_panel = QtWidgets.QWidget()
        side = QtWidgets.QVBoxLayout(control_panel)
        side.setContentsMargins(6, 0, 6, 0)
        self.controls_scroll.setWidget(control_panel)
        self.splitter.addWidget(self.controls_scroll)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([850, 450])
        connection_group = QtWidgets.QGroupBox('Local CCD connection')
        connection = QtWidgets.QGridLayout(connection_group)
        self.backend = QtWidgets.QComboBox(); self.backend.addItems(['Thorcam', 'Dummy'])
        self.backend.setCurrentText(self.options.get('backend', 'Thorcam'))
        self.serial = QtWidgets.QLineEdit(self.options.get('serial', '')); self.serial.setPlaceholderText('Camera serial (optional for one camera)')
        self.dll = QtWidgets.QLineEdit(self.options.get('dll_path', '')); self.dll.setPlaceholderText('ThorCam DLL directory (default if empty)')
        self.connect_button = QtWidgets.QPushButton('Connect local CCD')
        self.disconnect_button = QtWidgets.QPushButton('Disconnect')
        connection.addWidget(self.backend, 0, 0, 1, 2)
        connection.addWidget(self.serial, 1, 0, 1, 2)
        connection.addWidget(self.dll, 2, 0, 1, 2)
        connection.addWidget(self.connect_button, 3, 0)
        connection.addWidget(self.disconnect_button, 3, 1)
        side.addWidget(connection_group)
        self.connect_button.clicked.connect(self._connect)
        self.disconnect_button.clicked.connect(lambda: self.api.disconnect())
        self.status = QtWidgets.QLabel('Disconnected · Local camera; no InstrumentServer')
        self.status.setWordWrap(True); side.addWidget(self.status)

        camera_group = QtWidgets.QGroupBox('Acquisition')
        controls = QtWidgets.QGridLayout(camera_group)
        self.exposure = self._number(.01, 60000, 30, decimals=2)
        self.gain = self._number(0, 10000, 0)
        apply_camera = QtWidgets.QPushButton('Apply camera')
        self.start_button = QtWidgets.QPushButton('Start live')
        stop = QtWidgets.QPushButton('Stop acquisition')
        self.frames = self._number(1, 50, 1)
        capture = QtWidgets.QPushButton('Single / N frames')
        self.autosave = QtWidgets.QCheckBox('Auto-save TIFF')
        for row, (label, widget) in enumerate([('Exposure ms', self.exposure), ('Gain', self.gain), ('Frames', self.frames)]):
            controls.addWidget(QtWidgets.QLabel(label), row, 0); controls.addWidget(widget, row, 1)
        controls.addWidget(apply_camera, 3, 0); controls.addWidget(capture, 3, 1)
        controls.addWidget(self.start_button, 4, 0); controls.addWidget(stop, 4, 1)
        controls.addWidget(self.autosave, 5, 0, 1, 2)
        side.addWidget(camera_group)
        apply_camera.clicked.connect(lambda: self.api.configure(exposure_ms=self.exposure.value(), gain=self.gain.value()))
        self.start_button.clicked.connect(lambda: self.api.start_acquisition())
        stop.clicked.connect(lambda: self.api.stop_acquisition())
        capture.clicked.connect(self._capture)

        analysis = QtWidgets.QGroupBox('Ion detection')
        grid = QtWidgets.QGridLayout(analysis)
        self.threshold = self._number(0, 65535, 1000)
        self.area = self._number(0, 100000, 3, decimals=1)
        self.target = self._number(1, 10000, 1)
        self.consecutive = self._number(1, 10000, 3)
        self.timeout = self._number(.1, 86400, 60, decimals=1)
        for row, (label, widget) in enumerate([('Threshold >', self.threshold), ('Min contour area', self.area),
                                                 ('Target ≥', self.target), ('Consecutive frames', self.consecutive), ('Timeout s', self.timeout)]):
            grid.addWidget(QtWidgets.QLabel(label), row, 0); grid.addWidget(widget, row, 1)
        self.roi_enabled = QtWidgets.QCheckBox('Detection ROI · native sensor coordinates')
        self.roi = [self._number(0, 4096, v) for v in (0, 0, 320, 240)]
        grid.addWidget(self.roi_enabled, 5, 0, 1, 2)
        roi_row = QtWidgets.QGridLayout()
        for index, (label, widget) in enumerate(zip(('x1', 'y1', 'x2', 'y2'), self.roi)):
            roi_row.addWidget(QtWidgets.QLabel(label), index // 2, (index % 2)*2)
            roi_row.addWidget(widget, index // 2, (index % 2)*2+1)
        grid.addLayout(roi_row, 6, 0, 1, 2)
        apply_detection = QtWidgets.QPushButton('Apply detection')
        wait = QtWidgets.QPushButton('Wait for ions')
        cancel = QtWidgets.QPushButton('Cancel wait')
        grid.addWidget(apply_detection, 7, 0, 1, 2)
        grid.addWidget(wait, 8, 0); grid.addWidget(cancel, 8, 1)
        self.condition = QtWidgets.QLabel('Condition: not evaluated'); self.condition.setWordWrap(True)
        grid.addWidget(self.condition, 9, 0, 1, 2)
        apply_detection.clicked.connect(self._detection)
        wait.clicked.connect(self._wait)
        cancel.clicked.connect(lambda: self._watch.request_cancel() if self._watch else None)
        side.addWidget(analysis)

        display_group = QtWidgets.QGroupBox('Display')
        display = QtWidgets.QGridLayout(display_group)
        self.auto_levels = QtWidgets.QCheckBox('Auto levels'); self.auto_levels.setChecked(True)
        self.low = self._number(0, 65535, 0); self.high = self._number(0, 65535, 4095)
        self.flip_h = QtWidgets.QCheckBox('Flip H'); self.flip_v = QtWidgets.QCheckBox('Flip V')
        self.markers_enabled = QtWidgets.QCheckBox('Ion markers'); self.markers_enabled.setChecked(True)
        self.color = QtWidgets.QComboBox(); self.color.addItems(['grey', 'viridis', 'inferno'])
        fit = QtWidgets.QPushButton('Fit image')
        display.addWidget(self.auto_levels, 0, 0); display.addWidget(self.markers_enabled, 0, 1)
        display.addWidget(QtWidgets.QLabel('Min / Max'), 1, 0)
        levels = QtWidgets.QHBoxLayout(); levels.addWidget(self.low); levels.addWidget(self.high)
        display.addLayout(levels, 1, 1)
        display.addWidget(self.flip_h, 2, 0); display.addWidget(self.flip_v, 2, 1)
        display.addWidget(self.color, 3, 0); display.addWidget(fit, 3, 1)
        side.addWidget(display_group)
        self.canvas = pg.PlotWidget(viewBox=CCDViewBox())
        self.canvas.setProperty('handlesWheelZoom', True)
        self.canvas.setMinimumSize(400, 400)
        self.canvas.setAspectLocked(True)
        self.canvas.invertY(True)
        self.canvas.setLabel('bottom', 'Sensor x'); self.canvas.setLabel('left', 'Sensor y')
        self.image = pg.ImageItem(axisOrder='row-major')
        self.image.setAutoDownsample(True)
        self.canvas.addItem(self.image)
        self.markers = pg.ScatterPlotItem(symbol='o', size=14, pen=pg.mkPen('r', width=2), brush=None)
        self.canvas.addItem(self.markers)
        image_layout.addWidget(self.canvas, 1)
        fit.clicked.connect(lambda: self.canvas.autoRange())
        self.color.currentTextChanged.connect(self._colormap)
        for widget in (self.auto_levels, self.flip_h, self.flip_v, self.markers_enabled): widget.toggled.connect(self._needs_redraw)
        for widget in (self.low, self.high): widget.valueChanged.connect(self._needs_redraw)
        self.canvas.scene().sigMouseClicked.connect(self._pixel)
        self.telemetry = QtWidgets.QLabel('No frames'); self.telemetry.setWordWrap(True)
        image_layout.addWidget(self.telemetry)

        save_group = QtWidgets.QGroupBox('Save images')
        saving = QtWidgets.QGridLayout(save_group)
        self.directory = QtWidgets.QLineEdit(str(Path(__file__).resolve().parents[3] / 'data' / 'ccd'))
        browse = QtWidgets.QPushButton('Directory')
        save = QtWidgets.QPushButton('Save TIFF / PNG')
        self.save_sequence = QtWidgets.QCheckBox('Buffered sequence')
        self.save_roi = QtWidgets.QCheckBox('Detection ROI only')
        saving.addWidget(self.directory, 0, 0, 1, 2)
        saving.addWidget(browse, 1, 0); saving.addWidget(save, 1, 1)
        saving.addWidget(self.save_sequence, 2, 0); saving.addWidget(self.save_roi, 2, 1)
        side.addWidget(save_group)
        side.addStretch(1)
        browse.clicked.connect(self._directory)
        save.clicked.connect(self._save)
        # Existing device tabs can make the shared tab widget very tall. Keep
        # CCD controls compact; put surplus height below them, not between rows.
        layout.addStretch(1)
        self.timer = QtCore.QTimer(self); self.timer.setInterval(33)
        self.timer.timeout.connect(self._preview); self.timer.start()

    @staticmethod
    def _number(low, high, value, decimals=None):
        widget = QtWidgets.QSpinBox() if decimals is None else QtWidgets.QDoubleSpinBox()
        if decimals is not None: widget.setDecimals(decimals)
        widget.setRange(low, high); widget.setValue(value)
        return widget

    @property
    def connected(self): return self.worker.available

    def settings(self):
        return {'backend': self.backend.currentText(), 'serial': self.serial.text().strip(), 'dll_path': self.dll.text().strip()}

    def _connect(self):
        if not self.worker.isRunning():
            self.worker._closing = False
            self.worker.start()
        self.status.setText('Connecting local CCD…')
        self.api.connect(**self.settings())

    def _connected(self, info):
        self.status.setText(f"Connected: {info['backend']} · {info['shape'][1]} × {info['shape'][0]}")
        self.exposure.setValue(info['exposure_ms']); self.gain.setValue(info['gain'])
        self.frames.setMaximum(info['max_frames'])
        self.roi[2].setValue(info['shape'][1]); self.roi[3].setValue(info['shape'][0])
        self._last_frame = None
        self.condition.setText('Condition: not evaluated')
        self._detection()

    def _disconnected(self, message):
        self.status.setText(message)
        self.condition.setText('Condition unavailable: CCD disconnected')
        self._last_frame = None
        self.image.clear()
        self.markers.clear()

    def _state(self, state):
        self.status.setText('Acquiring' if state.get('running') else 'Connected · acquisition stopped')

    def _detection(self):
        roi = tuple(widget.value() for widget in self.roi) if self.roi_enabled.isChecked() else None
        self.api.configure_detection(threshold=self.threshold.value(), min_area=self.area.value(), target=self.target.value(), roi=roi)

    def _wait(self):
        if self._watch and not self._watch.done.is_set():
            self.condition.setText('An ion wait is already active'); return
        self._watch = self.api.wait_for_ions(self.target.value(), consecutive_frames=self.consecutive.value(), timeout_s=self.timeout.value())
        self.condition.setText('Waiting for fresh consecutive detections…')

    def _capture(self):
        path = str(Path(self.directory.text()) / (datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.tif')) if self.autosave.isChecked() else None
        self.api.capture(self.frames.value(), timeout_s=self.timeout.value(), save_path=path)

    def _completed(self, handle):
        if not handle.done.is_set():
            if handle.action == 'CCD_WAIT': self.condition.setText('Waiting for fresh consecutive detections…')
            return
        if handle.action == 'CCD_WAIT':
            self.condition.setText(str(handle.error) if handle.error else
                f"TRUE · {handle.result['count']} ions · {handle.result['consecutive_frames']} consecutive frames · frame {handle.result['frame_id']}")
        if not handle.error and handle.action == 'CCD_CONFIGURE':
            self.exposure.setValue(handle.result['exposure_ms']); self.gain.setValue(handle.result['gain'])
        if not handle.error and handle.action == 'CCD_DETECTION':
            self.threshold.setValue(handle.result['threshold']); self.area.setValue(handle.result['min_area'])
            self.target.setValue(handle.result['target'])
            roi = handle.result['roi']
            self.roi_enabled.setChecked(roi is not None)
            if roi:
                for widget, value in zip(self.roi, roi): widget.setValue(value)
        if handle.error:
            self.status.setText(f'{handle.action}: {handle.error}')
        elif handle.action in ('CCD_SAVE', 'CCD_CAPTURE'):
            self.log_message.emit(f'{handle.action} complete: {handle.result}')

    def _needs_redraw(self, *_): self._redraw = True

    def _colormap(self, name):
        self.image.setLookupTable(None if name == 'grey' else pg.colormap.get(name).getLookupTable())
        self._redraw = True

    def _preview(self):
        if not self.isVisible(): return
        snapshot = self.worker.latest_preview()
        if snapshot is None: return
        if snapshot['frame_id'] == self._last_frame and not self._redraw: return
        first_frame = self._last_frame is None
        self._last_frame = snapshot['frame_id']; self._redraw = False
        image = snapshot['image']
        if self.flip_h.isChecked(): image = image[:, ::-1]
        if self.flip_v.isChecked(): image = image[::-1]
        levels = (snapshot['raw_min'], snapshot['raw_max']) if self.auto_levels.isChecked() else (self.low.value(), self.high.value())
        if levels[1] <= levels[0]: levels = (levels[0], levels[0]+1)
        self.image.setImage(image, autoLevels=False, levels=levels)
        if first_frame: self.canvas.autoRange()
        centers = snapshot['centers'].copy()
        if len(centers) and self.markers_enabled.isChecked():
            if self.flip_h.isChecked(): centers[:, 0] = image.shape[1]-1-centers[:, 0]
            if self.flip_v.isChecked(): centers[:, 1] = image.shape[0]-1-centers[:, 1]
            self.markers.setData(x=centers[:, 0]+.5, y=centers[:, 1]+.5)
        else: self.markers.clear()
        age_ms = (time.perf_counter_ns()-snapshot['received_ns'])/1e6
        analysis_ms = (snapshot['analyzed_ns']-snapshot['received_ns'])/1e6
        self.telemetry.setText(f"Ions: {snapshot['count']} / {snapshot['target']} · frame {snapshot['frame_id']} · received→display {age_ms:.1f} ms · read+analysis {analysis_ms:.1f} ms · min/max {snapshot['raw_min']}/{snapshot['raw_max']}")

    def _pixel(self, event):
        snapshot = self.worker.latest_preview()
        if snapshot is None: return
        point = self.canvas.plotItem.vb.mapSceneToView(event.scenePos())
        x, y = int(point.x()), int(point.y())
        image = snapshot['image']; h, w = image.shape
        if 0 <= x < w and 0 <= y < h:
            if self.flip_h.isChecked(): x = w-1-x
            if self.flip_v.isChecked(): y = h-1-y
            self.status.setText(f'Native sensor pixel ({x}, {y}): {image[y, x]}')

    def _directory(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, 'CCD save directory', self.directory.text())
        if path: self.directory.setText(path)

    def _save(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save CCD image', str(Path(self.directory.text())/'capture.tif'), 'TIFF (*.tif);;PNG (*.png)')
        if path: self.api.save(path, sequence=self.save_sequence.isChecked(), roi_only=self.save_roi.isChecked())

    def still_running(self): return self.worker.isRunning()
    def shutdown(self):
        self.timer.stop()
        self.worker.shutdown()
