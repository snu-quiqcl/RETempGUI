from labremote.devices.ds1052e.tab import DS1052ETab
from labremote.devices.mso7054.worker import MSO7054Worker
import csv
import time
from collections import deque
from datetime import datetime, timezone
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from labremote.devices.ds1052e.tab import COLORS
from labremote.data_paths import DATA_ROOT, tab_data_directory
from PyQt5 import QtWidgets
from labremote.runtime.parameters import LIBRARY


class MSO7054Tab(DS1052ETab):
    channels=('CH1','CH2','CH3','CH4')
    worker_type=MSO7054Worker
    scope_title='MSO7054 four-channel screen acquisition'
    sample_note='MSO7054 screen samples with preamble calibration, not deep memory'
    display_on=True
    trigger_mode_path='trigger_type'
    trigger_sweep_path='sweep'
    first_measurement='vavg'
    first_measurement_title='Vavg'
    first_measurement_unit='V'
    slopes=('POS','NEG','RFAL')
    sweeps=('AUTO','NORM')
    shared_waveform_path='waveform_data'
    graph_display_controls=False

    def _build(self):
        super()._build()
        box=QtWidgets.QGroupBox('Additional measurements');grid=QtWidgets.QGridLayout(box)
        self.extra_measurements={}
        for n,ch in enumerate(self.channels):
            grid.addWidget(QtWidgets.QLabel(ch),n,0)
            for column,field in enumerate(('vrms','vmax','vmin'),start=1):
                label=QtWidgets.QLabel(field.upper()+': Unknown')
                self.extra_measurements[ch.lower()+'_'+field]=label;grid.addWidget(label,n,column)
        self.layout().addWidget(box)
        termination = QtWidgets.QGroupBox('Channel input impedance')
        grid = QtWidgets.QGridLayout(termination)
        self.impedance_controls = {}
        for row, ch in enumerate(self.channels):
            combo = QtWidgets.QComboBox()
            combo.addItem('High impedance (1 MΩ)', 'OMEG'); combo.addItem('50 Ω', 'FIFT')
            read = QtWidgets.QPushButton('Read'); apply = QtWidgets.QPushButton('Apply ' + ch)
            actual = QtWidgets.QLabel('Unknown')
            read.clicked.connect(lambda checked=False, c=ch: self.api.acquire(c.lower() + '_impedance'))
            apply.clicked.connect(lambda checked=False, c=ch: self.api.configure_impedance(c, self.impedance_controls[c][0].currentData()))
            self.impedance_controls[ch] = (combo, read, apply, actual)
            for col, widget in enumerate((QtWidgets.QLabel(ch), combo, read, apply, actual)):
                grid.addWidget(widget, row, col)
        self.layout().addWidget(termination)
        # Keep the detailed scope controls on their own page.
        outer = self.layout(); page = QtWidgets.QWidget(); content = QtWidgets.QVBoxLayout(page)
        while outer.count():
            item = outer.takeAt(0)
            if item.widget() is not None:
                content.addWidget(item.widget())
            elif item.layout() is not None:
                child = item.layout(); child.setParent(None); content.addLayout(child)
            else:
                content.addItem(item)
        self.pages = QtWidgets.QTabWidget(); outer.addWidget(self.pages)
        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(page)
        self.pages.addTab(scroll, 'Waveform / controls')
        history_page = QtWidgets.QWidget(); layout = QtWidgets.QVBoxLayout(history_page)
        self.pages.addTab(history_page, 'Peak History')
        note = QtWidgets.QLabel('Peak = maximum calibrated voltage of the received screen waveform, per channel. Shows the latest 100 points; CSV keeps the full run. Uses the same live waveform stream.')
        note.setWordWrap(True); layout.addWidget(note)
        row = QtWidgets.QHBoxLayout(); layout.addLayout(row)
        self.track_start = QtWidgets.QPushButton('Start tracking')
        self.track_stop = QtWidgets.QPushButton('Stop tracking')
        self.clear_peak = QtWidgets.QPushButton('Clear graph')
        self.save_peak = QtWidgets.QCheckBox('Save CSV while tracking')
        self.save_peak.setChecked(True)
        for widget in (self.track_start, self.track_stop, self.clear_peak, self.save_peak): row.addWidget(widget)
        self.peak_status = QtWidgets.QLabel('Stopped'); layout.addWidget(self.peak_status)
        self.peak_folder = DATA_ROOT / 'mso7054' / self.device_name / 'peak_history'
        self.peak_save_location = QtWidgets.QLabel('Save folder: ' + str(self.peak_folder))
        self.peak_save_location.setWordWrap(True)
        from PyQt5 import QtCore
        self.peak_save_location.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self.peak_save_location)
        self.peak_figure = Figure(); self.peak_canvas = FigureCanvasQTAgg(self.peak_figure)
        layout.addWidget(self.peak_canvas, 1)
        self.peak_axis = self.peak_figure.add_subplot(111)
        self.peak_axis.set_xlabel('Elapsed time (s)'); self.peak_axis.set_ylabel('Peak voltage (V)')
        self.peak_axis.grid(True, alpha=.25)
        self.peak_lines = {ch: self.peak_axis.plot([], [], label=ch, color=COLORS[ch])[0] for ch in self.channels}
        self.peak_axis.legend()
        self.peak_history = {ch: deque(maxlen=100) for ch in self.channels}
        self.tracking = False; self._peak_file = None; self._peak_seen = deque(maxlen=128)
        self.track_start.clicked.connect(self._start_peak)
        self.track_stop.clicked.connect(self._stop_peak)
        self.clear_peak.clicked.connect(self._clear_peak)
        self._buttons()

    def _settings(self,data,source):
        super()._settings(data,source)
        for path,label in self.extra_measurements.items():
            state=LIBRARY.read((self.worker._execution_device,path))
            value=state.observed if self.connected and state.quality=='valid' else None
            label.setText(path.split('_')[1].upper()+': '+('Unavailable' if value is None else f'{value:.8g} V'))

    def _buttons(self):
        super()._buttons()
        for combo, read, apply, actual in getattr(self, 'impedance_controls', {}).values():
            for widget in (combo, read, apply): widget.setEnabled(self.connected and not self.worker.has_requests())
        if hasattr(self, 'track_start'):
            self.track_start.setEnabled(self.connected and not self.tracking)
            self.track_stop.setEnabled(self.tracking)
            self.save_peak.setEnabled(not self.tracking)

    def _start_peak(self):
        channels = tuple(ch for ch, cb in self.ch_checks.items() if cb.isChecked())
        if not self.connected or not channels:
            self.peak_status.setText('Connect and enable a channel first'); return
        if self.tracking: return
        try:
            if self.save_peak.isChecked():
                folder = tab_data_directory(self.peak_folder, 'mso7054', self.device_name, 'peak_history'); folder.mkdir(parents=True, exist_ok=True)
                path = folder / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.csv')
                self._peak_file = path.open('x', newline='', encoding='utf-8')
                self._peak_writer = csv.writer(self._peak_file)
                self._peak_writer.writerow(['time_utc','elapsed_s','channel','max_v','min_v','vpp_v','samples'])
                self.peak_status.setToolTip(str(path))
                self.peak_save_location.setText('CSV file: ' + str(path))
            else:
                self.peak_save_location.setText('CSV saving OFF — folder: ' + str(self.peak_folder))
            self._clear_peak(); self._peak_origin = time.monotonic(); self.tracking = True
            if not self.worker.waveform_runner.running():
                self.api.start_waveform(channels, interval_s=self.period.value()/1000)
            self.peak_status.setText('Tracking'); self._buttons()
        except Exception as error:
            self._stop_peak(); self.peak_status.setText(str(error))

    def _stop_peak(self):
        self.tracking = False
        if self._peak_file is not None:
            file, self._peak_file = self._peak_file, None
            file.close()
        self.peak_status.setText('Stopped'); self._buttons()

    def _clear_peak(self):
        for values in self.peak_history.values(): values.clear()
        if not self.tracking: self._peak_origin = time.monotonic()
        for line in self.peak_lines.values(): line.set_data([], [])
        self.peak_canvas.draw_idle()

    def _record_peak(self):
        elapsed = time.monotonic() - self._peak_origin
        timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
        latest = []
        for ch, (_, volts) in self.traces.items():
            values = np.asarray(volts); finite = values[np.isfinite(values)]
            if not finite.size: continue
            maximum, minimum = float(finite.max()), float(finite.min())
            self.peak_history[ch].append((elapsed, maximum))
            self.peak_lines[ch].set_data(*zip(*self.peak_history[ch]))
            latest.append(f'{ch}: {maximum:.8g} V')
            if self._peak_file is not None:
                self._peak_writer.writerow([timestamp, elapsed, ch, maximum, minimum, maximum-minimum, len(values)])
        if self._peak_file is not None: self._peak_file.flush()
        self.peak_status.setText(' | '.join(latest))
        self.peak_axis.relim(); self.peak_axis.autoscale_view(); self.peak_canvas.draw_idle()

    def _handle_changed(self, handle):
        unseen = handle.request_id not in self._seen
        previous = self._last_waveform_completion
        super()._handle_changed(handle)
        if not handle.done.is_set() or not unseen: return
        if handle.action == 'IMPEDANCE':
            self.traces.clear(); self.trace_scales.clear(); self._render()
        if handle.action == 'IMPEDANCE' or handle.action.startswith('ACQUIRE ch'):
            for ch, (combo, read, apply, actual) in self.impedance_controls.items():
                state = LIBRARY.read((self.worker._execution_device, ch.lower()+'_impedance'))
                value = state.observed if state.quality == 'valid' and state.verification not in ('pending','failed','mismatch') else None
                actual.setText({'OMEG':'1 MΩ', 'FIFT':'50 Ω'}.get(value, 'Unknown'))
                if value in ('OMEG', 'FIFT'): combo.setCurrentIndex(combo.findData(value))
        if self.tracking and handle.action == 'FETCH':
            if handle.error is not None:
                self._stop_peak(); return
            if self._last_waveform_completion > previous and self.traces and all(
                    self.traces.get(ch) is trace for ch, trace in handle.result['traces'].items()):
                try: self._record_peak()
                except OSError as error:
                    self._stop_peak(); self.peak_status.setText('CSV error: ' + str(error))

    def _waveform_changed(self, handle):
        super()._waveform_changed(handle)
        if handle is self.worker.waveform_runner.handle and handle.done.is_set() and self.tracking:
            self._stop_peak()

    def _disconnected(self, message):
        self._stop_peak()
        for combo, read, apply, actual in self.impedance_controls.values(): actual.setText('Unknown')
        super()._disconnected(message)

    def shutdown(self):
        self._stop_peak()
        super().shutdown()
