"""Photon-count display; acquisition runs in the common FPGA worker/runner."""
from collections import deque
import csv
from datetime import datetime, timezone
from pathlib import Path
import time
import weakref
from PyQt5 import QtCore, QtWidgets
from labremote.api.devices import device_api
from labremote.devices.fpga.controller import INPUTS


class FPGACountTab(QtWidgets.QWidget):
    columns = ('time_utc', 'elapsed_s', 'channel', 'exposure_ms', 'average', 'mean_count', 'total_count')

    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self.worker = worker
        self.api = device_api(worker)
        self.samples = deque(maxlen=20)
        self.connected = False
        self.run_handle = None
        self.once_handle = None
        self.seen_results = weakref.WeakValueDictionary()
        self.log_path = None
        self.log_error = None
        self.started = None
        root = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout(); root.addLayout(row)
        self.channel = QtWidgets.QComboBox()
        for channel, (name, pin) in INPUTS.items(): self.channel.addItem(name+' / '+pin, channel)
        self.exposure = QtWidgets.QDoubleSpinBox(); self.exposure.setRange(.1, 6000)
        self.exposure.setDecimals(1); self.exposure.setValue(100)
        self.average = QtWidgets.QSpinBox(); self.average.setRange(1, 1000); self.average.setValue(1)
        self.interval = QtWidgets.QDoubleSpinBox(); self.interval.setRange(0, 3600); self.interval.setValue(.5)
        for title, field in [('Input port', self.channel), ('Exposure (ms)', self.exposure),
                             ('Average', self.average), ('Pause after point (s)', self.interval)]:
            row.addWidget(QtWidgets.QLabel(title)); row.addWidget(field)
        row = QtWidgets.QHBoxLayout(); root.addLayout(row)
        self.logging = QtWidgets.QCheckBox('Save CSV log')
        self.directory = QtWidgets.QLineEdit(str(Path(__file__).resolve().parents[2]/'logs'/'fpga_counts'))
        self.browse = QtWidgets.QPushButton('Folder…'); self.browse.clicked.connect(self.choose_directory)
        for widget in (self.logging, self.directory, self.browse): row.addWidget(widget)
        row = QtWidgets.QHBoxLayout(); root.addLayout(row)
        self.once = QtWidgets.QPushButton('Read once'); self.start = QtWidgets.QPushButton('Start')
        self.stop = QtWidgets.QPushButton('Stop')
        for widget in (self.once, self.start, self.stop): row.addWidget(widget)
        self.once.clicked.connect(lambda: self.begin(False)); self.start.clicked.connect(lambda: self.begin(True))
        self.stop.clicked.connect(self.cancel)
        self.count = QtWidgets.QLabel('Photon count: Unknown'); root.addWidget(self.count)
        self.timing = QtWidgets.QLabel('Timing: waiting'); self.timing.setWordWrap(True); root.addWidget(self.timing)
        self.status = QtWidgets.QLabel('Disconnected'); self.status.setWordWrap(True); root.addWidget(self.status)
        root.addWidget(QtWidgets.QLabel('Each point is the mean of N exposures. Plot: latest 20 points. CSV: all points.'))
        row=QtWidgets.QHBoxLayout();root.addLayout(row)
        self.y_auto=QtWidgets.QCheckBox('Auto Y min/max');self.y_auto.setChecked(True)
        self.y_min=QtWidgets.QDoubleSpinBox();self.y_max=QtWidgets.QDoubleSpinBox()
        for field in (self.y_min,self.y_max):
            field.setDecimals(3);field.setRange(-1e12,1e12)
        self.y_max.setValue(1000)
        row.addWidget(self.y_auto)
        for label,field in (('Y min',self.y_min),('Y max',self.y_max)):
            row.addWidget(QtWidgets.QLabel(label));row.addWidget(field)
        self.y_error=QtWidgets.QLabel();row.addWidget(self.y_error)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        self.figure = Figure(figsize=(9, 3)); self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumHeight(260); root.addWidget(self.canvas, 1)
        self.axis = self.figure.add_subplot(111); self.curve, = self.axis.plot([], [], marker='o')
        self.axis.set_xlabel('Elapsed seconds'); self.axis.set_ylabel('Mean photon count / exposure')
        self.axis.grid(True, alpha=.3); self.figure.tight_layout()
        self.y_auto.toggled.connect(self.update_y_range)
        self.y_min.valueChanged.connect(self.update_y_range);self.y_max.valueChanged.connect(self.update_y_range)
        self.update_y_range()
        worker.connected.connect(self.on_connected); worker.disconnected.connect(self.on_disconnected)
        worker.handle_changed.connect(self.on_result); worker.waveform_changed.connect(self.on_repeat)
        self.settle_timer=QtCore.QTimer(self);self.settle_timer.setInterval(25)
        self.settle_timer.timeout.connect(self.controls)
        worker.task_changed.connect(self.controls)
        self.controls()

    def update_y_range(self,*args):
        automatic=self.y_auto.isChecked()
        self.y_min.setEnabled(not automatic);self.y_max.setEnabled(not automatic)
        self.y_error.setText('')
        if automatic:
            self.axis.set_autoscaley_on(True)
        else:
            self.axis.set_autoscaley_on(False)
            low,high=self.y_min.value(),self.y_max.value()
            if low>=high:
                self.y_error.setText('Y min must be less than Y max')
            else:self.axis.set_ylim(low,high)
        self.axis.relim();self.axis.autoscale_view(scalex=True,scaley=automatic)
        self.canvas.draw_idle()

    def choose_directory(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, 'CSV log folder', self.directory.text())
        if path: self.directory.setText(path)

    def controls(self, *args):
        busy = (self.worker.waveform_runner.running() or
                (self.once_handle is not None and not self.once_handle.done.is_set()))
        scanning = any(r.running() for r in self.worker.scan_runners.values())
        settling = any(r.running() and r.handle is not None and r.handle.done.is_set()
                       for r in self.worker.scan_runners.values())
        if settling and not self.settle_timer.isActive():self.settle_timer.start()
        elif not settling:self.settle_timer.stop()
        self.start.setEnabled(self.connected and not busy and not scanning)
        self.once.setEnabled(self.connected and not busy and not scanning)
        self.stop.setEnabled(busy)
        for field in (self.channel, self.exposure, self.average, self.interval, self.logging, self.directory, self.browse):
            field.setEnabled(not busy)

    def on_connected(self, *args):
        self.connected = True; self.status.setText('Ready'); self.controls()

    def on_disconnected(self, message):
        self.connected = False; self.count.setText('Photon count: Unknown')
        self.status.setText(message); self.controls()

    def begin(self, repeat):
        if not self.connected or self.worker.waveform_runner.running(): return
        if self.once_handle is not None and not self.once_handle.done.is_set(): return
        self.log_path = None
        self.log_error = None
        try:
            if self.logging.isChecked():
                folder = Path(self.directory.text()).expanduser(); folder.mkdir(parents=True, exist_ok=True)
                path = folder / ('counts_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.csv')
                with path.open('x', newline='', encoding='utf-8') as stream:
                    csv.writer(stream).writerow(self.columns)
                self.log_path = path
        except OSError as exc:
            self.status.setText('Log file could not be created: '+str(exc)); return
        self.samples.clear(); self.seen_results.clear(); self.started = time.monotonic()
        self.curve.set_data([], []); self.canvas.draw_idle(); self.count.setText('Photon count: Waiting')
        self.run_handle = self.once_handle = None
        args = (self.channel.currentData(), self.exposure.value(), self.average.value())
        if repeat: self.run_handle = self.api.start_count_tracking(*args, interval_s=self.interval.value())
        else: self.once_handle = self.api.measure_counts(*args)
        self.status.setText('Measuring'+(' — '+str(self.log_path) if self.log_path else ''))
        self.controls()

    def cancel(self):
        if self.run_handle is not None and not self.run_handle.done.is_set(): self.run_handle.request_cancel()
        if self.once_handle is not None and not self.once_handle.done.is_set(): self.once_handle.request_cancel()

    def on_result(self, handle):
        if handle.action != 'MEASURE_COUNTS' or not handle.done.is_set(): return
        owner = getattr(handle.group, 'waveform_run_id', None)
        if handle is not self.once_handle and not (self.run_handle and owner == self.run_handle.request_id): return
        if handle.request_id in self.seen_results: return
        self.seen_results[handle.request_id] = handle
        if handle.error is not None:
            self.status.setText(self.log_error or ('Stopped: '+str(handle.error))); self.controls(); return
        value = handle.result; elapsed = value['monotonic_s']-self.started
        spacing_ms = (elapsed - self.samples[-1][0]) * 1000 if self.samples else None
        stages = value.get('timings_ms', {})
        self.timing.setText('Timing (ms, sum of exposures): ' + ', '.join(
            f'{name}={duration:.2f}' for name, duration in stages.items()) +
            f"; operation={value.get('operation_ms', 0):.2f}" +
            (f'; point interval={spacing_ms:.2f}' if spacing_ms is not None else ''))
        self.samples.append((elapsed, value['count']))
        self.count.setText(f"Photon count: {value['count']:g} / {value['ms']:g} ms (average {value['average']})")
        self.curve.set_data([p[0] for p in self.samples], [p[1] for p in self.samples])
        self.axis.relim(); self.axis.autoscale_view(); self.canvas.draw_idle()
        if self.log_path:
            try:
                with self.log_path.open('a', newline='', encoding='utf-8') as stream:
                    csv.writer(stream).writerow((value['time_utc'], elapsed,
                        value['channel'], value['ms'], value['average'], value['count'], value['total_count']))
            except OSError as exc:
                self.log_error='Logging failed; acquisition stopped: '+str(exc)
                self.cancel(); self.status.setText(self.log_error)
                self.log_path = None
        if handle is self.once_handle and not self.log_error:
            self.status.setText('Completed'+(' — '+str(self.log_path) if self.log_path else ''))
        self.controls()

    def on_repeat(self, handle):
        if handle is not self.run_handle: return
        self.status.setText(self.log_error or ('Tracking: '+handle.status+(' — '+str(self.log_path) if self.log_path else '')))
        self.controls()
        if handle.done.is_set() and self.worker.waveform_runner.running():
            QtCore.QTimer.singleShot(50, lambda: self.on_repeat(handle))
