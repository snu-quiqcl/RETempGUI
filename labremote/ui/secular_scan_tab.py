"""Micromotion subpage: AFG frequency scan, no DAC controls."""
import json
from pathlib import Path
from PyQt5 import QtCore, QtWidgets as W
from labremote.devices.fpga.mapping import bound_methods
from labremote.api.devices import device_api
from labremote.devices.dac.model import atomic_json
from labremote.data_paths import tab_data_directory
from labremote.micromotion.secular import config
from labremote.micromotion.secular.plotting import draw


@bound_methods(None)
class SecularScanPage(W.QWidget):
    def __init__(self,worker,bindings,parent=None):
        super().__init__(parent)
        self.worker=worker;self.bindings=bindings;self.api=device_api(worker)
        self.setObjectName('micromotion_secular')
        self.fields={};self._sources={};self.report=None;self.pending=None;self.selected=None;self.axes={}
        root=W.QVBoxLayout(self)
        note=W.QLabel('Fixed DAC · AFG2105 sine excitation · SYNC–PMT first-photon fit · Cooling outputs unchanged')
        note.setWordWrap(True);root.addWidget(note)
        split=W.QSplitter();root.addWidget(split,1)
        scroll=W.QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumWidth(340);split.addWidget(scroll)
        self.settings_panel=W.QWidget();scroll.setWidget(self.settings_panel);form=W.QFormLayout(self.settings_panel)
        form.setRowWrapPolicy(W.QFormLayout.WrapAllRows);form.setFieldGrowthPolicy(W.QFormLayout.AllNonFixedFieldsGrow)
        self.chamber=W.QComboBox();self.chamber.addItems(['EC','EA']);form.addRow('Chamber / saved settings',self.chamber)
        self.source=W.QComboBox();self.source.setObjectName('secular_afg_source');form.addRow('Connected AFG2105',self.source)
        for key,label,pins in [('trg_pin','Modulation SYNC',config.STOPWATCH_PINS),
                               ('pmt_pin','PMT (count + timing)',tuple(p for p in config.STOPWATCH_PINS if p in config.COUNTER_PINS))]:
            box=W.QComboBox()
            for pin in pins:box.addItem(pin+' · '+config.PINS[pin],pin)
            box.setObjectName('secular_'+key);self.fields[key]=box;form.addRow(label,box)
        for key,label,decimals in [
            ('start_khz','Start frequency (kHz)',3),('stop_khz','Stop frequency (kHz)',3),
            ('step_khz','Frequency step (kHz)',3),('amplitude_dbm','AFG amplitude (dBm)',6),
            ('offset_v','AFG DC offset (V)',6),('settle_s','Frequency settling (s)',3),
            ('target_events','Target events / point',0),('phase_bins','Phase bins',0),
            ('point_timeout_s','Timeout / point (s)',1),('max_attempts','Maximum attempts / point',0),
            ('block_attempts','Attempts / FPGA block',0),('count_exposure_us','Count live time / repeat (µs)',0),
            ('count_repeats','Count-rate repeats',0),('max_background_m','Maximum first-event background M',3)]:
            box=W.QDoubleSpinBox() if decimals else W.QSpinBox()
            if decimals:box.setDecimals(decimals)
            box.setRange(*(config.FLOATS[key] if decimals else config.INTS[key]))
            box.setKeyboardTracking(False);box.setObjectName('secular_'+key)
            self.fields[key]=box;form.addRow(label,box)
        action=W.QComboBox();action.addItem('Stop scan','stop');action.addItem('Warn and continue','warn')
        self.fields['rate_action']=action;form.addRow('Count-rate limit action',action)
        fit_note=W.QLabel('Fit: First-photon corrected. Mean count rate is measured at every frequency. AFG output is switched OFF on completion, Stop or failure.')
        fit_note.setWordWrap(True);form.addRow(fit_note)
        self.save_button=W.QPushButton('Save settings');self.load_button=W.QPushButton('Load saved settings')
        form.addRow(self.save_button);form.addRow(self.load_button)
        self.save_button.clicked.connect(self.save_settings);self.load_button.clicked.connect(self.load_settings)
        right=W.QWidget();split.addWidget(right);layout=W.QVBoxLayout(right)
        row=W.QHBoxLayout();layout.addLayout(row)
        self.run=W.QPushButton('Start frequency scan');self.stop=W.QPushButton('Stop / save partial')
        row.addWidget(self.run);row.addWidget(self.stop)
        self.run.clicked.connect(self.start);self.stop.clicked.connect(self.api.stop_micromotion)
        self.status=W.QLabel('Connect FPGA and AFG2105, then select the physical SYNC and PMT inputs.')
        self.status.setWordWrap(True);layout.addWidget(self.status)
        self.progress_bar=W.QProgressBar();layout.addWidget(self.progress_bar)
        row=W.QHBoxLayout();layout.addLayout(row)
        self.directory=W.QLineEdit(str(tab_data_directory(None,'micromotion')))
        self.folder_button=W.QPushButton('Save folder');self.open_button=W.QPushButton('Open result')
        row.addWidget(self.directory,1);row.addWidget(self.folder_button);row.addWidget(self.open_button)
        self.folder_button.clicked.connect(self.choose_folder);self.open_button.clicked.connect(self.open_result)
        self.metrics=W.QLabel('');self.metrics.setWordWrap(True);layout.addWidget(self.metrics)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg,NavigationToolbar2QT
        self.figure=Figure(figsize=(10,7));self.canvas=FigureCanvasQTAgg(self.figure)
        layout.addWidget(NavigationToolbar2QT(self.canvas,self));layout.addWidget(self.canvas,1)
        self.canvas.mpl_connect('button_press_event',self.select_point)
        worker.task_progress.connect(self.progress)
        self.chamber.currentTextChanged.connect(self.change_chamber)
        self.load_settings()
        self.timer=QtCore.QTimer(self);self.timer.setInterval(500);self.timer.timeout.connect(self.tick);self.timer.start()
        split.setSizes([360,900]);self.tick();self.render()
        from labremote.ui.experiment_sidebar import install_settings_toggle
        self.settings_toggle=install_settings_toggle(split,scroll)
        self.settings_toggle.setChecked(True)

    def populate(self,c):
        c=config.validate(c)
        self.chamber.blockSignals(True);self.chamber.setCurrentText(c['chamber']);self.chamber.blockSignals(False)
        for key,box in self.fields.items():
            if isinstance(box,W.QComboBox):box.setCurrentIndex(box.findData(c[key]))
            else:box.setValue(c[key])
        self.preferred_source=c.get('afg_name','');self.refresh_sources()

    def value(self):
        c=dict(schema_version=1,chamber=self.chamber.currentText(),afg_name=self.source.currentData() or '')
        c.update({key:box.currentData() if isinstance(box,W.QComboBox) else box.value() for key,box in self.fields.items()})
        return config.validate(c)

    def refresh_sources(self):
        sources={bridge.worker.name:bridge.worker for family,bridge in self.bindings().values() if family=='afg2105'}
        chosen=self.source.currentData() or self.preferred_source
        if list(sources)!=[self.source.itemData(i) for i in range(self.source.count())]:
            self.source.clear()
            for name in sources:self.source.addItem(name,name)
            index=self.source.findData(chosen)
            if index>=0:self.source.setCurrentIndex(index)
        self._sources=sources

    def start(self):
        try:
            c=self.value();afg=self._sources.get(self.source.currentData())
            if not self.directory.text().strip():raise ValueError('Choose a result folder')
            handle=self.api.run_secular_scan(settings=c,afg=afg,directory=self.directory.text())
            if handle.done.is_set() and handle.error:raise handle.error
            self.selected=None;self.report=None;self.status.setText('Starting secular frequency scan');self.controls()
        except Exception as exc:self.status.setText(str(exc))

    def controls(self):
        w=self.worker;running=w.secular_runner.running()
        busy=w.has_requests() or any(t.running() for t in w._background_tasks)
        source=self._sources.get(self.source.currentData())
        ready=source is not None and source.ps is not None and not source.connection_error and not source._closing
        self.run.setEnabled(w.ps is not None and not w.connection_error and not w._closing and not busy and ready)
        self.stop.setEnabled(running or w.micromotion_runner.running());self.settings_panel.setEnabled(not running)
        for widget in (self.directory,self.folder_button,self.open_button):widget.setEnabled(not running)

    def progress(self,label,state):
        if label!='SECULAR_SCAN' or state.get('run_id')!=self.worker.secular_runner.state.get('run_id'):return
        if 'report' in state:self.pending=state['report']
        if state.get('error'):self.status.setText(state['error'])

    def tick(self):
        if not self.worker.secular_runner.running():
            try:self.refresh_sources()
            except Exception as exc:self.status.setText('Source list: '+str(exc))
        if self.pending is not None:
            self.report=self.pending;self.pending=None
            self.render()
        self.controls()

    def render(self):
        report=self.report or dict(points=[],settings=config.defaults())
        self.axes=draw(self.figure,report,self.selected);self.canvas.draw_idle()
        if self.report is None:return
        r=self.report;current=r.get('current_point');points=r.get('points',[])
        self.progress_bar.setRange(0,r.get('planned_points',1));self.progress_bar.setValue(len(points))
        text=f"{r.get('status','')} · {len(points)}/{r.get('planned_points','?')} frequencies · {r.get('cleanup','')}"
        if current:text+=f"\n{current['frequency_khz']:.6g} kHz · {current.get('events',0):,} events · {current.get('attempts',0):,} attempts"
        self.status.setText(text+'\n'+r.get('folder','')+'\n'+r.get('error','')+' '+r.get('cleanup_error',''))
        p=points[self.selected] if self.selected is not None and self.selected<len(points) else current or (points[-1] if points else None)
        if p and p.get('fit',{}).get('valid'):
            f=p['fit'];m=f['modulation'];se=f.get('modulation_se')
            phase='unresolved' if f.get('phase_rad') is None else f"{f['phase_rad']:.4g} rad"
            error_text=f'{100*se:.3g}%' if se is not None else 'unresolved'
            self.metrics.setText(f"{p['frequency_khz']:.6g} kHz · modulation {100*m:.4g}% ± {error_text} · phase {phase}"+
                ('\n'+p['warning'] if p.get('warning') else ''))
        else:self.metrics.setText(p.get('warning','') if p else '')

    def select_point(self,event):
        if event.inaxes not in (self.axes.get('amplitude'),self.axes.get('phase'),self.axes.get('rate')) or event.xdata is None:return
        points=(self.report or {}).get('points',[])
        if points:self.selected=min(range(len(points)),key=lambda i:abs(points[i]['frequency_khz']-event.xdata));self.render()

    def change_chamber(self):self.load_settings()

    def load_settings(self):
        try:self.populate(config.load(self.chamber.currentText()))
        except Exception as exc:
            self.populate(config.defaults(self.chamber.currentText()));self.status.setText('Settings: '+str(exc))

    def save_settings(self):
        try:
            c=self.value();atomic_json(config.settings_file(c['chamber']),c);self.status.setText('Secular scan settings saved')
        except Exception as exc:self.status.setText(str(exc))

    def choose_folder(self):
        path=W.QFileDialog.getExistingDirectory(self,'Secular scan results',self.directory.text())
        if path:self.directory.setText(path)

    def open_result(self):
        path,_=W.QFileDialog.getOpenFileName(self,'Open secular scan',self.directory.text(),'Results (results.json)')
        if path:
            try:
                r=json.loads(Path(path).read_text(encoding='utf-8'))
                if r.get('experiment')!='secular_frequency_scan' or r.get('schema_version')!=1:raise ValueError('Not a secular frequency scan result')
                config.validate(r['settings']);self.report=r;self.selected=None;self.render()
            except Exception as exc:self.status.setText(str(exc))

    def shutdown(self):
        self.timer.stop();self.worker.secular_runner.cancel()
