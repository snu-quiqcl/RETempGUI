from pathlib import Path
from PyQt5 import QtCore,QtWidgets
from labremote.api.devices import device_api
from labremote.characterization import config,rabi,pulse_experiment as model

class PulseExperimentTab(QtWidgets.QWidget):
    def __init__(self,worker,kind,chamber,bindings,parent=None):
        super().__init__(parent);self.kind=kind;self.worker=worker;self.chamber=chamber;self.bindings=bindings;self.api=device_api(worker)
        self.fields={};self.roles={};self.run_id=None;self.rendered_id=None;self.live={};self.live_axis=None;self.live_lines={};self.config_buttons=[]
        root=QtWidgets.QVBoxLayout(self)
        note=QtWidgets.QLabel('EC FPGA · '+chamber+' '+model.title(kind)+' · MW 주파수·출력은 외부 설정 · 종료/중단: FPGA MW gate LOW, 선택 광로 cooling 상태 복귀');note.setWordWrap(True);root.addWidget(note)
        split=QtWidgets.QSplitter();root.addWidget(split,1)
        scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumWidth(330);split.addWidget(scroll)
        settings=QtWidgets.QWidget();scroll.setWidget(settings);left=QtWidgets.QVBoxLayout(settings)
        form=QtWidgets.QFormLayout();left.addLayout(form)
        for key,title,lo,hi,dec,step in model.fields(kind):
            field=QtWidgets.QDoubleSpinBox() if dec else QtWidgets.QSpinBox()
            if dec:field.setDecimals(dec)
            field.setRange(lo,hi);field.setSingleStep(step);self.fields[key]=field;form.addRow(title,field)
        mapping=QtWidgets.QGroupBox('이 실험의 FPGA 역할 매핑');mapping_form=QtWidgets.QFormLayout(mapping);left.addWidget(mapping)
        for role,names in rabi.ROLE_CHOICES.items():
            box=QtWidgets.QComboBox();box.addItems(names);self.roles[role]=box;mapping_form.addRow(role,box)
        for title,callback in [('조건·매핑 불러오기',self.load),('조건·매핑 저장',self.save),('다른 이름으로 저장',self.save_as)]:
            button=QtWidgets.QPushButton(title);button.clicked.connect(callback);left.addWidget(button);self.config_buttons.append(button)
        left.addStretch()
        result=QtWidgets.QWidget();right=QtWidgets.QVBoxLayout(result);split.addWidget(result);split.setSizes([350,750])
        row=QtWidgets.QHBoxLayout();right.addLayout(row)
        self.start_button=QtWidgets.QPushButton('Run '+chamber+' '+model.title(kind));self.stop_button=QtWidgets.QPushButton('Stop / save partial')
        self.start_button.clicked.connect(self.start);self.stop_button.clicked.connect(getattr(self.api,"stop_"+kind));row.addWidget(self.start_button);row.addWidget(self.stop_button)
        self.directory=QtWidgets.QLineEdit(str(Path(__file__).resolve().parents[2]/'data/characterization'));right.addWidget(self.directory)
        row=QtWidgets.QHBoxLayout();right.addLayout(row)
        for title,callback in [('저장 폴더',self.choose_folder),('이전 결과 열기',self.load_result)]:
            button=QtWidgets.QPushButton(title);button.clicked.connect(callback);row.addWidget(button)
        self.status=QtWidgets.QLabel('대기 중');self.status.setWordWrap(True);right.addWidget(self.status)
        self.summary=QtWidgets.QLabel();self.summary.setWordWrap(True);right.addWidget(self.summary)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        self.figure=Figure(figsize=(8,9));self.canvas=FigureCanvasQTAgg(self.figure);self.canvas.setMinimumSize(300,400);right.addWidget(self.canvas,1)
        self.config_valid=False
        try:self.populate(model.load(kind,chamber));self.config_valid=True
        except Exception as exc:self.status.setText(str(exc))
        self.timer=QtCore.QTimer(self);self.timer.setInterval(500);self.timer.timeout.connect(self.controls);self.timer.start()
        worker.task_progress.connect(self.progress);self.controls()

    def populate(self,value):
        for key,field in self.fields.items():field.setValue(value[key]*.01 if key in model.times(self.kind) else value[key])
        for role,box in self.roles.items():box.setCurrentText(value['roles'][role])

    def value(self):
        values={k:round(f.value()*100) if k in model.times(self.kind) else f.value() for k,f in self.fields.items()}
        return model.validate(self.kind,dict(schema_version=1,experiment=self.kind,chamber=self.chamber,roles={r:b.currentText() for r,b in self.roles.items()},**values))

    def load(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Load '+model.title(self.kind)+' settings',str(config.ROOT),'JSON (*.json)')
        if path:
            try:self.populate(model.load(self.kind,self.chamber,path));self.config_valid=True;self.status.setText('불러옴: '+path)
            except Exception as exc:self.status.setText(str(exc))

    def save(self):
        try:
            path=config.ROOT/f'{self.kind}_{self.chamber}.local.json';config.save(path,self.value());self.config_valid=True;self.status.setText('저장됨: '+str(path))
        except Exception as exc:self.status.setText(str(exc))

    def save_as(self):
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Save '+model.title(self.kind)+' settings',str(config.ROOT/f'{self.kind}_{self.chamber}.local.json'),'JSON (*.json)')
        if path:
            try:config.save(path,self.value());self.status.setText('저장됨: '+path)
            except Exception as exc:self.status.setText(str(exc))

    def choose_folder(self):
        path=QtWidgets.QFileDialog.getExistingDirectory(self,'Result folder',self.directory.text())
        if path:self.directory.setText(path)

    def start(self):
        try:
            c=self.value()
            if not self.directory.text().strip():raise ValueError('결과 저장 폴더를 지정하세요.')
            handle=getattr(self.api,"run_"+self.kind)(self.chamber,settings=c,directory=self.directory.text())
            if handle.done.is_set() and handle.error:raise handle.error
            self.run_id=handle.request_id;self.rendered_id=None;self.live={};self.live_axis=None;self.live_lines={};self.figure.clear();self.canvas.draw_idle();self.summary.clear();self.status.setText('Starting · '+self.run_id)
        except Exception as exc:self.status.setText(str(exc))
        self.controls()

    def controls(self):
        runner=getattr(self.worker,self.kind+"_runner");active=runner.running()
        busy=self.worker.has_requests() or self.worker.waveform_runner.running() or any(t.running() for t in self.worker._background_tasks)
        self.start_button.setEnabled(self.config_valid and self.worker.ps is not None and not self.worker.connection_error and not self.worker._closing and not busy)
        self.stop_button.setEnabled(active and runner.settings['settings']['chamber']==self.chamber)
        for field in (*self.fields.values(),*self.roles.values(),*self.config_buttons):field.setEnabled(not active)

    def progress(self,label,state):
        runner=getattr(self.worker,self.kind+'_runner')
        if label!=self.kind.upper() or state.get('chamber')!=self.chamber or state.get('run_id')!=runner.state.get('run_id'):return
        if self.run_id!=state['run_id']:
            self.rendered_id=None;self.figure.clear();self.canvas.draw_idle();self.summary.clear()
        self.run_id=state['run_id'];self.status.setText(f"{state.get('phase','')} · {state.get('points',0)}/{state.get('total','?')} · {state.get('received_samples',0)} received · {state.get('folder','')}"+(' · '+state['error'] if state.get('error') else ''))
        if state.get('analysis') is not None and self.rendered_id!=self.run_id:
            try:self.show_result(state['analysis'],state['result'])
            except Exception as exc:self.status.setText('Result saved; display error: '+str(exc))
            self.rendered_id=self.run_id

    def show_result(self,data,report):
        model.draw(self.figure,data);self.canvas.draw_idle()
        self.summary.setText(f"{report['chamber']} {model.title(self.kind)} · {report['status']} · {report['completed_points']} complete points/batches\n"+model.summary(data))

    def load_result(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Open '+model.title(self.kind)+' result',self.directory.text(),'Result (result.json)')
        if path:
            try:
                report=config.read(path)
                if report['chamber']!=self.chamber or report.get('experiment')!=self.kind:raise ValueError('Result chamber differs from tab')
                self.show_result(config.read(Path(path).parent/'analysis.json'),report);self.status.setText(path)
            except Exception as exc:self.status.setText(str(exc))
