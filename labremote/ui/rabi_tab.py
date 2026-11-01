from pathlib import Path
from PyQt5 import QtCore,QtWidgets
from labremote.api.devices import Devices,device_api
from labremote.characterization import config,rabi

class RabiTab(QtWidgets.QWidget):
    def __init__(self,worker,chamber,bindings,parent=None):
        super().__init__(parent);self.worker=worker;self.chamber=chamber;self.bindings=bindings;self.api=device_api(worker)
        self.fields={};self.roles={};self.run_id=None;self.rendered_id=None;self.live={};self.live_axis=None;self.live_lines={};self.config_buttons=[]
        root=QtWidgets.QVBoxLayout(self)
        note=QtWidgets.QLabel('EC FPGA · '+chamber+' microwave Rabi · 종료/중단: microwave OFF, MW gate LOW, 선택 광로 cooling 상태 복귀');note.setWordWrap(True);root.addWidget(note)
        split=QtWidgets.QSplitter();root.addWidget(split,1)
        scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumWidth(330);split.addWidget(scroll)
        settings=QtWidgets.QWidget();scroll.setWidget(settings);left=QtWidgets.QVBoxLayout(settings)
        form=QtWidgets.QFormLayout();left.addLayout(form)
        self.microwave=QtWidgets.QLineEdit('apsyn420_mw');form.addRow('Microwave instrument',self.microwave)
        self.connection=QtWidgets.QLabel();self.connection.setWordWrap(True);form.addRow(self.connection)
        for key,title,lo,hi,dec,step in [
            ('frequency_start_hz','Frequency start (Hz)',1e4,20e9,3,1000),('frequency_stop_hz','Frequency end (Hz)',1e4,20e9,3,1000),('frequency_step_hz','Frequency step (Hz)',.001,20e9,3,1000),
            ('T_cool','Cooling time (us)',0,655.35,2,1),('T_cool_repeat','Cooling repeats',1,65535,0,1),
            ('WAIT_AOM','AOM wait (us)',0,655.35,2,.1),('T_init','Initialization (us)',0,655.35,2,1),('T_det','Detection (us)',0,655.35,2,1),
            ('T_mw_step','Pulse time step (us)',.07,655.35,2,1),('N_qubit_control','Pulse points (from 0)',3,65535,0,1),
            ('N_average','Shots / point',1,1024,0,1),('N_threshold','Bright threshold (>=)',0,65535,0,1),
            ('settle_s','Frequency settle (s)',0,60,3,.1),('timeout_s','Timeout / point (s)',.1,3600,1,1)]:
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
        self.start_button=QtWidgets.QPushButton('Run '+chamber+' Rabi');self.stop_button=QtWidgets.QPushButton('Stop / save partial')
        self.start_button.clicked.connect(self.start);self.stop_button.clicked.connect(self.api.stop_rabi);row.addWidget(self.start_button);row.addWidget(self.stop_button)
        self.directory=QtWidgets.QLineEdit(str(Path(__file__).resolve().parents[2]/'data/characterization'));right.addWidget(self.directory)
        row=QtWidgets.QHBoxLayout();right.addLayout(row)
        for title,callback in [('저장 폴더',self.choose_folder),('이전 결과 열기',self.load_result)]:
            button=QtWidgets.QPushButton(title);button.clicked.connect(callback);row.addWidget(button)
        self.status=QtWidgets.QLabel('대기 중');self.status.setWordWrap(True);right.addWidget(self.status)
        self.summary=QtWidgets.QLabel();self.summary.setWordWrap(True);right.addWidget(self.summary)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        self.figure=Figure(figsize=(8,9));self.canvas=FigureCanvasQTAgg(self.figure);right.addWidget(self.canvas,1)
        self.config_valid=False
        try:self.populate(rabi.load(chamber));self.config_valid=True
        except Exception as exc:self.status.setText(str(exc))
        self.timer=QtCore.QTimer(self);self.timer.setInterval(500);self.timer.timeout.connect(self.controls);self.timer.start()
        worker.task_progress.connect(self.progress);self.controls()

    def populate(self,value):
        self.microwave.setText(value['microwave'])
        for key,field in self.fields.items():field.setValue(value[key]*.01 if key in rabi.TIMES else value[key])
        for role,box in self.roles.items():box.setCurrentText(value['roles'][role])

    def value(self):
        values={k:round(f.value()*100) if k in rabi.TIMES else f.value() for k,f in self.fields.items()}
        return rabi.validate(dict(schema_version=1,chamber=self.chamber,microwave=self.microwave.text().strip(),roles={r:b.currentText() for r,b in self.roles.items()},**values))

    def load(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Load Rabi settings',str(config.ROOT),'JSON (*.json)')
        if path:
            try:self.populate(rabi.load(self.chamber,path));self.config_valid=True;self.status.setText('불러옴: '+path)
            except Exception as exc:self.status.setText(str(exc))

    def save(self):
        try:
            path=config.ROOT/f'rabi_{self.chamber}.local.json';config.save(path,self.value());self.config_valid=True;self.status.setText('저장됨: '+str(path))
        except Exception as exc:self.status.setText(str(exc))

    def save_as(self):
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Save Rabi settings',str(config.ROOT/f'rabi_{self.chamber}.local.json'),'JSON (*.json)')
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
            microwave=Devices(self.bindings()).anapico(c['microwave'])
            handle=self.api.run_rabi(self.chamber,microwave,settings=c,directory=self.directory.text())
            if handle.done.is_set() and handle.error:raise handle.error
            self.run_id=handle.request_id;self.rendered_id=None;self.live={};self.live_axis=None;self.live_lines={};self.figure.clear();self.canvas.draw_idle();self.summary.clear();self.status.setText('Starting · '+self.run_id)
        except KeyError:self.status.setText('장비 구성에서 선택한 AnaPico를 추가하고 연결하세요.')
        except Exception as exc:self.status.setText(str(exc))
        self.controls()

    def controls(self):
        runner=self.worker.rabi_runner;active=runner.running()
        try:
            microwave=Devices(self.bindings()).anapico(self.microwave.text().strip()).worker
            connected=microwave.ps is not None and not microwave.connection_error
        except KeyError:connected=False
        self.connection.setText('Microwave 연결됨' if connected else 'Microwave 미연결 · 메인 장비 구성에서 추가/연결')
        busy=self.worker.has_requests() or self.worker.waveform_runner.running() or any(t.running() for t in self.worker._background_tasks)
        self.start_button.setEnabled(self.config_valid and connected and self.worker.ps is not None and not self.worker.connection_error and not self.worker._closing and not busy)
        self.stop_button.setEnabled(active and runner.settings['settings']['chamber']==self.chamber)
        for field in (*self.fields.values(),*self.roles.values(),*self.config_buttons,self.microwave):field.setEnabled(not active)

    def progress(self,label,state):
        if label!='RABI' or state.get('chamber')!=self.chamber or state.get('run_id')!=self.worker.rabi_runner.state.get('run_id'):return
        if self.run_id!=state['run_id']:self.live={};self.live_axis=None;self.live_lines={};self.rendered_id=None;self.summary.clear()
        self.run_id=state['run_id'];self.status.setText(f"{state.get('phase','')} · {state.get('points',0)}/{state.get('total','?')} · {state.get('folder','')}"+(' · '+state['error'] if state.get('error') else ''))
        if state.get('analysis') is not None and self.rendered_id!=self.run_id:
            self.show_result(state['analysis'],state['result']);self.rendered_id=self.run_id
        elif state.get('latest_point') and self.rendered_id!=self.run_id:
            p=state['latest_point'];self.live[p['frequency_hz'],p['time_us']]=p['population']
            if self.live_axis is None:
                self.figure.clear();self.live_axis=self.figure.add_subplot(111)
                self.live_axis.set(xlabel='Nominal microwave pulse time (us)',ylabel='Bright population',ylim=(-.05,1.05))
            ax=self.live_axis
            for frequency in sorted({k[0] for k in self.live}):
                rows=sorted((t,v) for (f,t),v in self.live.items() if f==frequency)
                if frequency not in self.live_lines:self.live_lines[frequency],=ax.plot([],[],'o-',label=f'{frequency/1e9:.9f} GHz');ax.legend()
                self.live_lines[frequency].set_data([p[0] for p in rows],[p[1] for p in rows])
            ax.relim();ax.autoscale_view(scalex=True,scaley=False);self.canvas.draw_idle()

    def show_result(self,data,report):
        rabi.draw(self.figure,data);self.canvas.draw_idle()
        lines=[f"{report['chamber']} · {report['status']} · {report['completed_points']} points"]
        for curve in data['curves']:
            f=curve['fit'];lines.append(f"{curve['frequency_hz']/1e9:.9f} GHz: "+(f"Rabi {f['frequency_hz']/1000:.4g} kHz, π time {f['pi_time_us']:.4g} us" if f['valid'] else 'Fit unavailable: '+f['reason']))
        self.summary.setText('\n'.join(lines))

    def load_result(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Open Rabi result',self.directory.text(),'Result (result.json)')
        if path:
            try:
                report=config.read(path)
                if report['chamber']!=self.chamber:raise ValueError('Result chamber differs from tab')
                self.show_result(config.read(Path(path).parent/'analysis.json'),report);self.status.setText(path)
            except Exception as exc:self.status.setText(str(exc))
