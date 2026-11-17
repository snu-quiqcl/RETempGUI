"""Independent SPAM 2D Scan editor and live result viewer."""
from pathlib import Path
import numpy as np
from PyQt5 import QtCore, QtWidgets as W
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from labremote.characterization import config, pulse_experiment as spam, spam_scan as model
from labremote.devices.fpga.mapping import bound_methods
from labremote.data_paths import characterization_directory
from labremote.api.devices import device_api


class AxisEditor(W.QGroupBox):
    changed = QtCore.pyqtSignal()

    def __init__(self, title, parent=None):
        super().__init__(title, parent)
        form = W.QFormLayout(self)
        self.family = W.QComboBox()
        for key, text in [('windfreak', '장비 · Windfreak'), ('sg384', '장비 · SG384'),
                          ('anapico', '장비 · AnaPico'), ('dds4', '장비 · DDS'), ('spam', 'SPAM 측정 파라미터')]:
            self.family.addItem(text, key)
        self.device = W.QComboBox()
        self.channel = W.QComboBox()
        self.parameter = W.QComboBox()
        from .responsive import bounded_combo
        for box in (self.family, self.device, self.channel, self.parameter): bounded_combo(box)
        for title, widget in [('대상 종류', self.family), ('장비', self.device), ('채널 / 출력', self.channel), ('파라미터', self.parameter)]:
            form.addRow(title, widget)
        self.start = W.QDoubleSpinBox()
        self.stop = W.QDoubleSpinBox()
        self.points = W.QSpinBox(); self.points.setRange(2, 501); self.points.setValue(11)
        self.settle = W.QDoubleSpinBox(); self.settle.setRange(0, 60000); self.settle.setSuffix(' ms'); self.settle.setValue(100)
        for title, field in [('Start', self.start), ('Stop', self.stop), ('Points', self.points), ('Settle', self.settle)]:
            field.setKeyboardTracking(False)
            form.addRow(title, field)
            field.valueChanged.connect(self.changed)
        self.workers = {}
        self.family.currentIndexChanged.connect(self.rebuild)
        self.parameter.currentIndexChanged.connect(self.range_changed)
        self.device.currentIndexChanged.connect(self.changed)
        self.channel.currentIndexChanged.connect(self.changed)
        self.rebuild()

    def refresh_devices(self, workers):
        self.workers = workers
        family = self.family.currentData()
        old = self.device.currentText()
        names = sorted(name for f, name in workers if f == family)
        if old and old not in names:
            names.append(old)
        if [self.device.itemText(i) for i in range(self.device.count())] != names:
            with QtCore.QSignalBlocker(self.device):
                self.device.clear(); self.device.addItems(names)
                if old: self.device.setCurrentText(old)

    def rebuild(self):
        family = self.family.currentData()
        with QtCore.QSignalBlocker(self.device): self.device.clear()
        self.refresh_devices(self.workers)
        with QtCore.QSignalBlocker(self.channel):
            self.channel.clear()
            for channel in model.CHANNELS[family]: self.channel.addItem(str(channel) or '—', channel)
        with QtCore.QSignalBlocker(self.parameter):
            self.parameter.clear()
            for key, p in model.PARAMETERS[family].items(): self.parameter.addItem(f'{p.title} ({p.unit})', key)
        for field in (self.device, self.channel, self.settle): field.setEnabled(family != 'spam')
        self.range_changed()

    def range_changed(self):
        family, key = self.family.currentData(), self.parameter.currentData()
        if key is None: return
        p = model.PARAMETERS[family][key]
        for field in (self.start, self.stop):
            with QtCore.QSignalBlocker(field):
                field.setDecimals(p.decimals); field.setRange(p.low, p.high); field.setSuffix(' ' + p.unit)
                field.setSingleStep(1 if p.decimals == 0 else .01 if family == 'spam' else 1)
        defaults = {'power': (-20, -8), 'frequency': (1995, 2005), 'vva': (300, 700),
                    'T_det': (40, 120), 'T_PI': (50, 100), 'T_init': (1, 3),
                    'T_cool': (100, 500), 'WAIT_AOM': (.1, 1.1)}
        lo, hi = defaults[key]
        if family == 'dds4' and key == 'frequency': lo, hi = 70, 90
        self.start.setValue(lo); self.stop.setValue(hi)
        self.points.setValue(13 if key == 'power' else 11)
        self.changed.emit()

    def value(self):
        family = self.family.currentData()
        return dict(family=family, device='' if family == 'spam' else self.device.currentText(),
                    channel=self.channel.currentData(), parameter=self.parameter.currentData(),
                    start=self.start.value(), stop=self.stop.value(), points=self.points.value(),
                    settle_s=0 if family == 'spam' else self.settle.value()/1000)

    def populate(self, axis):
        self.family.setCurrentIndex(self.family.findData(axis['family']))
        self.parameter.setCurrentIndex(self.parameter.findData(axis['parameter']))
        if self.device.findText(axis['device']) < 0 and axis['device']: self.device.addItem(axis['device'])
        self.device.setCurrentText(axis['device'])
        self.channel.setCurrentIndex(self.channel.findData(axis['channel']))
        self.start.setValue(axis['start']); self.stop.setValue(axis['stop']); self.points.setValue(axis['points'])
        self.settle.setValue(axis['settle_s']*1000)


@bound_methods('spam', editor=True)
class SpamScanTab(W.QWidget):
    def __init__(self, worker, chamber, bindings, parent=None):
        super().__init__(parent)
        self.worker, self.chamber, self.bindings = worker, chamber, bindings
        self.api = device_api(worker)
        self.fields, self.roles = {}, {}
        self.dataset = None; self.selected = None; self.run_id = None; self.revision = None
        root = W.QVBoxLayout(self)
        title = W.QLabel(f'<b>SPAM 2D Scan · {chamber}</b> — 두 파라미터를 바꾸며 SPAM을 측정합니다.')
        title.setWordWrap(True); root.addWidget(title)
        split = W.QSplitter(); root.addWidget(split, 1)
        scroll = W.QScrollArea(); scroll.setWidgetResizable(True); scroll.setMinimumWidth(350)
        self.settings_panel = W.QWidget(); left = W.QVBoxLayout(self.settings_panel); scroll.setWidget(self.settings_panel); split.addWidget(scroll)
        self.x = AxisEditor('X축'); self.y = AxisEditor('Y축')
        self.y.family.setCurrentIndex(self.y.family.findData('dds4'))
        left.addWidget(self.x); left.addWidget(self.y)
        fixed = W.QGroupBox('고정 SPAM 조건'); form = W.QFormLayout(fixed); left.addWidget(fixed)
        for key, title, lo, hi, dec, step in spam.fields('spam'):
            field = W.QDoubleSpinBox() if dec else W.QSpinBox()
            if dec: field.setDecimals(dec)
            field.setRange(lo, hi); field.setSingleStep(step); field.setKeyboardTracking(False)
            self.fields[key] = field; form.addRow(title, field)
        from .pulse_controls import pin_controls
        mapping, self.roles = pin_controls(worker, 'spam', self.settings_panel); left.addWidget(mapping)
        self.restore = W.QCheckBox('종료 / 중단 후 축 장비값 복원'); self.restore.setChecked(True); left.addWidget(self.restore)
        note = W.QLabel('DDS VVA는 광파워(mW)가 아닌 제어값입니다.\nThreshold는 스캔 전체에서 고정합니다.\nRF 출력 ON/OFF는 기존 장비 화면에서 설정하세요.'); note.setWordWrap(True); left.addWidget(note)
        for title, callback in [('2D 설정 불러오기', self.load), ('2D 설정 저장', self.save)]:
            b = W.QPushButton(title); b.clicked.connect(callback); left.addWidget(b)
        left.addStretch()
        right_panel = W.QWidget(); right = W.QVBoxLayout(right_panel); split.addWidget(right_panel); split.setSizes([380, 950])
        bar = W.QHBoxLayout(); right.addLayout(bar)
        self.start_button = W.QPushButton('새 스캔 시작'); self.start_button.clicked.connect(self.start)
        self.stop_button = W.QPushButton('Stop / 부분 결과 저장'); self.stop_button.clicked.connect(self.stop)
        self.open_button = W.QPushButton('이전 결과 열기'); self.open_button.clicked.connect(self.load_result)
        self.export_button = W.QPushButton('Heatmap 이미지 저장'); self.export_button.clicked.connect(self.export_image)
        for b in (self.start_button, self.stop_button, self.open_button, self.export_button): bar.addWidget(b)
        self.directory = W.QLineEdit(str(characterization_directory(None, chamber, 'spam_2d')))
        row = W.QHBoxLayout(); row.addWidget(self.directory); right.addLayout(row)
        browse = W.QPushButton('저장 폴더'); browse.clicked.connect(self.choose_folder); row.addWidget(browse); self.browse = browse
        self.status = W.QLabel('대기 중'); self.status.setWordWrap(True); right.addWidget(self.status)
        self.progress_bar = W.QProgressBar(); right.addWidget(self.progress_bar)
        self.metric = W.QComboBox()
        for key, title in model.METRICS.items(): self.metric.addItem(title, key)
        self.metric.currentIndexChanged.connect(self.redraw); right.addWidget(self.metric)
        self.figure = Figure(figsize=(8, 4)); self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumSize(400, 260); right.addWidget(self.canvas, 3)
        self.canvas.mpl_connect('button_press_event', self.select_cell)
        details = W.QGroupBox('선택한 지점'); detail = W.QHBoxLayout(details); right.addWidget(details, 2)
        self.hist_figure = Figure(figsize=(5, 2.5)); self.hist_canvas = FigureCanvasQTAgg(self.hist_figure)
        self.hist_canvas.setMinimumSize(280, 200); detail.addWidget(self.hist_canvas, 3)
        self.summary = W.QLabel('Heatmap의 셀을 클릭하면 상태별 히스토그램을 표시합니다.')
        self.summary.setWordWrap(True); self.summary.setMinimumWidth(180); detail.addWidget(self.summary, 2)
        self.hint = W.QLabel('회색: 미측정 / 유효 데이터 없음 · ×: 실패/중단 · Fidelity는 accepted sample 기준'); self.hint.setWordWrap(True); right.addWidget(self.hint)
        self.x.changed.connect(self.axis_changed); self.y.changed.connect(self.axis_changed)
        self.populate_spam(spam.load('spam', chamber))
        self.timer = QtCore.QTimer(self); self.timer.setInterval(500); self.timer.timeout.connect(self.controls); self.timer.start()
        worker.task_progress.connect(self.progress)
        self.controls()

    def workers(self):
        bindings = self.bindings() if callable(self.bindings) else self.bindings
        return {(family, bridge.worker.name): bridge.worker for family, bridge in bindings.values()}

    def populate_spam(self, c):
        for key, field in self.fields.items(): field.setValue(c[key]/100 if key in spam.times('spam') else c[key])
        for role, box in self.roles.items(): box.setCurrentText(c['roles'][role])

    def value(self):
        c = dict(schema_version=1, experiment='spam', chamber=self.chamber,
                 roles={role:box.route() for role, box in self.roles.items()})
        c.update({key:round(f.value()*100) if key in spam.times('spam') else f.value() for key,f in self.fields.items()})
        return model.validate(dict(schema_version=1, experiment='spam_2d', spam=c, x=self.x.value(), y=self.y.value(), restore=self.restore.isChecked()))

    def axis_changed(self):
        scanned = {a.parameter.currentData() for a in (self.x, self.y) if a.family.currentData() == 'spam'}
        for key, field in self.fields.items():
            field.setEnabled(key not in scanned)
            field.setToolTip('축 범위로 설정 중' if key in scanned else '')

    def controls(self):
        runner = self.worker.spam_scan_runner
        active = runner.running()
        workers = self.workers()
        if not active:
            for axis in (self.x, self.y): axis.refresh_devices(workers)
        ready = self.worker.ps is not None and not self.worker.connection_error and not self.worker._closing
        busy = self.worker.has_foreground_requests() or any(t.running() for t in self.worker._background_tasks)
        self.start_button.setEnabled(ready and not busy)
        self.stop_button.setEnabled(active and runner.settings['settings']['spam']['chamber'] == self.chamber)
        self.settings_panel.setEnabled(not active)
        for widget in (self.directory, self.browse, self.open_button): widget.setEnabled(not active)
        self.export_button.setEnabled(self.dataset is not None)
        if not active: self.axis_changed()

    def start(self):
        try:
            c = self.value()
            if not self.directory.text().strip(): raise ValueError('결과 저장 폴더를 지정하세요.')
            handle = self.api.run_spam_scan(settings=c, workers=self.workers(), directory=self.directory.text())
            if handle.done.is_set() and handle.error: raise handle.error
            self.run_id = handle.request_id; self.revision = None; self.selected = None
            self.dataset = dict(settings=c, records=[], folder=None)
            self.hist_figure.clear(); self.hist_canvas.draw_idle(); self.summary.setText('측정 중…')
            self.redraw(); self.status.setText('Starting · ' + self.run_id)
        except Exception as exc: self.status.setText(str(exc))
        self.controls()

    def stop(self): self.worker.spam_scan_runner.cancel()

    def progress(self, label, state):
        runner = self.worker.spam_scan_runner
        if label != 'SPAM_2D_SCAN' or state.get('chamber') != self.chamber or state.get('run_id') != runner.state.get('run_id'): return
        if self.run_id != state['run_id']:
            self.selected = None; self.revision = None
        self.run_id = state['run_id']
        self.status.setText(f"{state.get('phase', '')} · {state.get('points', 0)}/{state.get('total', 0)} · {state.get('folder', '')}" + (' · ' + state['error'] if state.get('error') else ''))
        self.progress_bar.setRange(0, state.get('total', 1)); self.progress_bar.setValue(state.get('points', 0))
        revision = (self.run_id, len(state.get('records', [])))
        if revision != self.revision:
            self.dataset = dict(settings=state['settings'], records=state.get('records', []), folder=state.get('folder'))
            self.revision = revision
            if self.selected is None and self.dataset['records']:
                p = self.dataset['records'][-1]; self.selected = (p['ix'], p['iy'])
            self.redraw()
        self.controls()

    def redraw(self):
        if self.dataset is None: return
        self.map_axis = model.draw_map(self.figure, self.dataset['settings'], self.dataset['records'], self.metric.currentData(), self.selected)
        self.canvas.draw_idle(); self.show_selected()

    def select_cell(self, event):
        if self.dataset is None or event.inaxes is not getattr(self, 'map_axis', None) or event.xdata is None: return
        c = self.dataset['settings']
        self.selected = (int(np.argmin(abs(np.array(model.axis_values(c['x'])) - event.xdata))),
                         int(np.argmin(abs(np.array(model.axis_values(c['y'])) - event.ydata))))
        self.redraw()

    def show_selected(self):
        if self.selected is None: return
        self.hist_figure.clear()
        p = next((p for p in self.dataset['records'] if (p['ix'], p['iy']) == self.selected), None)
        if p is None:
            self.summary.setText('아직 측정하지 않은 지점입니다.'); self.hist_canvas.draw_idle(); return
        title = f"X = {p['x']:g} / Y = {p['y']:g}\n{p['status']}"
        try:
            if not p.get('folder'): raise ValueError(p.get('error') or 'SPAM 데이터 없음')
            folder = Path(self.dataset['folder']).resolve()
            child = (folder / p['folder']).resolve()
            if not child.is_relative_to(folder): raise ValueError('Invalid point folder')
            data = config.read(child / 'analysis.json')
            ax = self.hist_figure.add_subplot(111)
            for state, color in zip(data['states'], ('#2474e8', '#f59438')):
                counts = np.asarray(state['counts'], dtype=int)
                bins = np.bincount(np.minimum(counts, 40), minlength=41)
                ax.bar(np.arange(41), bins, color=color, alpha=.65, label=f"State {state['condition']}")
            ax.axvline(data['threshold'], color=ax.xaxis.label.get_color(), linestyle='--', label='Threshold')
            maximum = max((max(s['counts'], default=0) for s in data['states']), default=0)
            ax.set(xlabel='Photon counts (40 = overflow)', ylabel='Samples', xlim=(-.5, min(40, max(10, maximum))+1))
            ax.legend(fontsize=8); self.hist_figure.subplots_adjust(left=.16, right=.98, bottom=.27, top=.95)
            def percent(v): return 'N/A' if v is None else f'{100*v:.3f}%'
            lines = [title, 'Average error: ' + percent(data['average_spam_error']), 'Fidelity: ' + percent(data['spam_fidelity'])]
            for s in data['states']:
                lines.append(f"State {s['condition']}: {percent(s['spam_error'])}\nAccepted / attempts: {s['N_success']} / {s['N_attempts']}\nReceived: {s['N_received']}")
            if p.get('error'): lines.append(p['error'])
            self.summary.setText('\n'.join(lines))
        except Exception as exc: self.summary.setText(title + '\n' + str(exc))
        self.hist_canvas.draw_idle()

    def choose_folder(self):
        path = W.QFileDialog.getExistingDirectory(self, 'Result folder', self.directory.text())
        if path: self.directory.setText(path)

    def save(self):
        try:
            c = self.value()
            path, _ = W.QFileDialog.getSaveFileName(self, 'Save SPAM 2D settings', f'spam_2d_{self.chamber}.json', 'JSON (*.json)')
            if path: config.save(path, c); self.status.setText('저장됨: ' + path)
        except Exception as exc: self.status.setText(str(exc))

    def load(self):
        path, _ = W.QFileDialog.getOpenFileName(self, 'Load SPAM 2D settings', '', 'JSON (*.json)')
        if not path: return
        try:
            c = model.validate(config.read(path))
            if c['spam']['chamber'] != self.chamber: raise ValueError('다른 챔버의 설정입니다.')
            self.populate_spam(c['spam']); self.x.populate(c['x']); self.y.populate(c['y']); self.restore.setChecked(c['restore'])
            self.axis_changed(); self.status.setText('불러옴: ' + path)
        except Exception as exc: self.status.setText(str(exc))

    def load_result(self):
        path, _ = W.QFileDialog.getOpenFileName(self, 'Open SPAM 2D result', self.directory.text(), 'Result (result.json)')
        if not path: return
        try:
            report = config.read(path); folder = Path(path).parent
            if report['experiment'] != 'spam_2d' or report['chamber'] != self.chamber: raise ValueError('다른 실험 / 챔버의 결과입니다.')
            settings = model.validate(config.read(folder / 'configuration.json')['settings'])
            self.dataset = dict(settings=settings, records=config.read(folder / 'points.json'), folder=str(folder))
            self.selected = None
            if self.dataset['records']:
                p = self.dataset['records'][0]; self.selected = (p['ix'], p['iy'])
            self.hist_figure.clear(); self.hist_canvas.draw_idle(); self.summary.clear()
            self.redraw(); self.status.setText(report['status'] + ' · ' + path)
            self.progress_bar.setRange(0, report['expected_points']); self.progress_bar.setValue(report['completed_points'])
        except Exception as exc: self.status.setText(str(exc))

    def export_image(self):
        if self.dataset is None: return
        path, _ = W.QFileDialog.getSaveFileName(self, 'Save heatmap', 'spam_2d_heatmap.png', 'PNG (*.png)')
        if path:
            try: self.figure.savefig(path, dpi=160); self.status.setText('저장됨: ' + path)
            except Exception as exc: self.status.setText(str(exc))

    def shutdown(self): self.timer.stop()
