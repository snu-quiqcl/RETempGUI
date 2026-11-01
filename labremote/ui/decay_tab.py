from pathlib import Path
from PyQt5 import QtCore,QtWidgets
from labremote.api.devices import device_api
from labremote.decay import config
from labremote.decay.plotting import DecayPlot

class DecayExperimentTab(QtWidgets.QWidget):
    def __init__(self,worker,chamber,mode,parent=None):
        super().__init__(parent);self.worker=worker;self.api=device_api(worker);self.chamber=chamber;self.mode=mode;self.fields={};self.roles={};self.run_id=None;self.plot=None;self.revision=-1
        root=QtWidgets.QVBoxLayout(self)
        note=QtWidgets.QLabel('171: initialization before pulse · 174: no EOM initialization · PMT − SYNC: 1.25 ns/bin · dashed curve: fixed lifetime reference, not a fit');note.setWordWrap(True);root.addWidget(note)
        split=QtWidgets.QSplitter();root.addWidget(split,1);scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumWidth(370);split.addWidget(scroll)
        left=QtWidgets.QWidget();scroll.setWidget(left);form=QtWidgets.QFormLayout(left)
        for key,label,lo,hi in config.FIELDS:
            box=QtWidgets.QDoubleSpinBox() if key in ('timeout_s','reference_tau_ns') else QtWidgets.QSpinBox();box.setRange(lo,hi)
            if isinstance(box,QtWidgets.QDoubleSpinBox):box.setDecimals(2)
            self.fields[key]=box;form.addRow(label,box)
        for role,choices in config.CHOICES.items():
            box=QtWidgets.QComboBox();box.addItems(choices);self.roles[role]=box;form.addRow(role,box)
        self.profile_buttons=[]
        for text,fn in [('Load settings / mapping',self.load),('Save settings / mapping',self.save),('Save as',self.save_as)]:
            b=QtWidgets.QPushButton(text);b.clicked.connect(fn);form.addRow(b);self.profile_buttons.append(b)
        right=QtWidgets.QWidget();split.addWidget(right);layout=QtWidgets.QVBoxLayout(right);row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        self.run=QtWidgets.QPushButton('Run '+chamber+' '+config.LABELS[mode]);self.stop=QtWidgets.QPushButton('Stop / save partial');row.addWidget(self.run);row.addWidget(self.stop)
        self.run.clicked.connect(self.start);self.stop.clicked.connect(self.api.stop_decay)
        self.directory=QtWidgets.QLineEdit(str(Path(__file__).resolve().parents[2]/'data/decay'));layout.addWidget(self.directory)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        for text,fn in [('Save folder',self.choose_folder),('Open result',self.load_result)]:
            b=QtWidgets.QPushButton(text);b.clicked.connect(fn);row.addWidget(b)
        self.status=QtWidgets.QLabel('Idle');self.status.setWordWrap(True);layout.addWidget(self.status)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        self.figure=Figure(figsize=(10,8));self.canvas=FigureCanvasQTAgg(self.figure);self.canvas.setMinimumSize(400,400);layout.addWidget(self.canvas,1);split.setSizes([420,900])
        try:self.populate(config.load(chamber,mode))
        except Exception as exc:self.populate(config.defaults(chamber,mode));self.status.setText(str(exc))
        worker.task_progress.connect(self.progress);self.timer=QtCore.QTimer(self);self.timer.timeout.connect(self.controls);self.timer.start(300);self.controls()
    def populate(self,c):
        for k,b in self.fields.items():b.setValue(c[k])
        for k,b in self.roles.items():b.setCurrentText(c['roles'][k])
    def value(self):return config.validate(dict(schema_version=1,chamber=self.chamber,mode=self.mode,roles={k:b.currentText() for k,b in self.roles.items()},**{k:b.value() for k,b in self.fields.items()}))
    def load(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Load decay settings',str(config.ROOT),'JSON (*.json)')
        if path:
            try:self.populate(config.load(self.chamber,self.mode,path));self.status.setText(path)
            except Exception as exc:self.status.setText(str(exc))
    def save(self):
        try:
            path=config.ROOT/f'{self.chamber}_{self.mode}.local.json';config.save(path,self.value());self.status.setText(str(path))
        except Exception as exc:self.status.setText(str(exc))
    def save_as(self):
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Save decay settings',str(config.ROOT/f'{self.chamber}_{self.mode}.local.json'),'JSON (*.json)')
        if path:
            try:config.save(path,self.value());self.status.setText(path)
            except Exception as exc:self.status.setText(str(exc))
    def choose_folder(self):
        path=QtWidgets.QFileDialog.getExistingDirectory(self,'Save folder',self.directory.text())
        if path:self.directory.setText(path)
    def start(self):
        try:
            if not self.directory.text().strip():raise ValueError('Choose a save folder')
            h=self.api.run_decay(self.chamber,self.mode,settings=self.value(),directory=self.directory.text())
            if h.done.is_set() and h.error:raise h.error
            self.plot=None;self.revision=-1;self.run_id=h.request_id;self.figure.clear();self.canvas.draw_idle();self.status.setText('Starting')
        except Exception as exc:self.status.setText(str(exc))
        self.controls()
    def controls(self):
        w=self.worker;r=w.decay_runner;busy=w.has_requests() or w.waveform_runner.running() or any(t.running() for t in w._background_tasks)
        self.run.setEnabled(w.ps is not None and not w.connection_error and not w._closing and not busy)
        self.stop.setEnabled(r.running() and (r.settings['settings']['chamber'],r.settings['settings']['mode'])==(self.chamber,self.mode))
        for b in (*self.fields.values(),*self.roles.values(),*self.profile_buttons):b.setEnabled(not r.running())
        self.roles['PMT2'].setEnabled(not r.running() and self.mode.endswith('dual'))
        for key in ('EOM_7G1','EOM_7G2','EOM_2G'):self.roles[key].setEnabled(not r.running() and self.mode.startswith('171'))
        self.fields['waiting_time_for_AOM_on'].setEnabled(not r.running() and self.mode.endswith('single'))
    def progress(self,label,state):
        r=self.worker.decay_runner
        if label!='DECAY' or (state.get('chamber'),state.get('mode'))!=(self.chamber,self.mode) or state.get('run_id')!=r.state.get('run_id'):return
        if self.run_id!=state['run_id']:self.run_id=state['run_id'];self.plot=None;self.revision=-1
        self.status.setText(f"{state.get('phase','')} · {state.get('completed_batches',0)}/{state.get('total','?')} batches · {state.get('folder','')}"+(' · '+state['error'] if state.get('error') else ''))
        data=state.get('live')
        if data is not None and data['chunks']!=self.revision:
            try:
                if self.plot is None:self.plot=DecayPlot(self.figure,r.settings['settings'])
                self.plot.update(data);self.canvas.draw_idle();self.revision=data['chunks']
            except Exception as exc:self.status.setText('Display: '+str(exc))
    def load_result(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Open decay result',self.directory.text(),'Result (result.json)')
        if path:
            try:
                p=Path(path);report=config.read(p)
                if report.get('experiment')!='decay' or (report['chamber'],report['mode'])!=(self.chamber,self.mode):raise ValueError('Result differs from tab')
                c=config.read(p.parent/'configuration.json')['settings'];self.plot=DecayPlot(self.figure,c);self.plot.update(config.read(p.parent/'histogram.json'));self.canvas.draw_idle();self.status.setText(report['status']+' · '+path)
            except Exception as exc:self.status.setText(str(exc))

class DecayTab(QtWidgets.QTabWidget):
    def __init__(self,worker,parent=None):
        super().__init__(parent);self.experiments={}
        for chamber in ('EA','EC'):
            tabs=QtWidgets.QTabWidget();self.addTab(tabs,chamber)
            for mode in config.MODES:
                panel=DecayExperimentTab(worker,chamber,mode,tabs);self.experiments[chamber,mode]=panel;tabs.addTab(panel,config.LABELS[mode])
    def shutdown(self):
        for panel in self.experiments.values():panel.timer.stop()
