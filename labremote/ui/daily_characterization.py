"""Daily experiment views share the existing FPGA worker and workflow API."""
from pathlib import Path
import numpy as np
from PyQt5 import QtCore,QtWidgets
from labremote.api.devices import device_api
from labremote.characterization import config
from labremote.characterization.fluorescence import draw


class MappingTab(QtWidgets.QWidget):
    def __init__(self,worker,parent=None):
        super().__init__(parent);self.worker=worker;self.fields={}
        root=QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel('EC 셋업의 공통 FPGA · fluorescence는 PMT만 사용하며 AOM 출력은 변경하지 않습니다.'))
        grid=QtWidgets.QGridLayout();root.addLayout(grid)
        for col,title in enumerate(('실험 대상','시퀀스 PMT','시퀀스 AOM')):grid.addWidget(QtWidgets.QLabel(title),0,col)
        for row,chamber in enumerate(('EA','EC'),1):
            grid.addWidget(QtWidgets.QLabel(chamber),row,0)
            for col,(role,names) in enumerate((('PMT',config.PMTS),('AOM',config.AOMS)),1):
                box=QtWidgets.QComboBox();box.addItems(names);self.fields[chamber,role]=box;grid.addWidget(box,row,col)
        row=QtWidgets.QHBoxLayout();root.addLayout(row)
        for title,callback in (('불러오기',self.load),('저장 / 적용',self.apply),('다른 이름으로 저장',self.save_as)):
            button=QtWidgets.QPushButton(title);row.addWidget(button);button.clicked.connect(callback)
        self.status=QtWidgets.QLabel();self.status.setWordWrap(True);root.addWidget(self.status);root.addStretch()
        try:self.populate(config.load_roles());self.status.setText(str(config.ROOT/'fpga_roles.local.json'))
        except Exception as exc:self.status.setText(str(exc))

    def populate(self,value):
        for (chamber,role),box in self.fields.items():box.setCurrentText(value['routes'][chamber][role])

    def value(self):
        return config.validate_roles(dict(schema_version=1,setup='EC',routes={c:{r:self.fields[c,r].currentText() for r in ('PMT','AOM')} for c in ('EA','EC')}))

    def idle(self):
        if self.worker.fluorescence_runner.running():raise RuntimeError('측정 종료 후 매핑을 변경하세요. 실행 중 매핑은 고정됩니다.')

    def load(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Load FPGA role mapping',str(config.ROOT),'JSON (*.json)')
        if path:
            try:self.idle();self.populate(config.load_roles(path));self.status.setText('불러옴 · 저장 / 적용을 눌러 활성화: '+path)
            except Exception as exc:self.status.setText(str(exc))

    def apply(self):
        try:
            self.idle();path=config.ROOT/'fpga_roles.local.json';config.save(path,self.value());self.status.setText('적용됨 · '+str(path))
        except Exception as exc:self.status.setText(str(exc))

    def save_as(self):
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Save mapping',str(config.ROOT/'fpga_roles.local.json'),'JSON (*.json)')
        if path:
            try:config.save(path,self.value());self.status.setText('파일 저장됨 · 활성화하려면 불러오기 후 저장 / 적용: '+path)
            except Exception as exc:self.status.setText(str(exc))


class FluorescenceTab(QtWidgets.QWidget):
    def __init__(self,worker,chamber,parent=None):
        super().__init__(parent);self.worker=worker;self.chamber=chamber;self.api=device_api(worker);self.fields={};self.run_id=None;self.rendered_id=None
        root=QtWidgets.QVBoxLayout(self);self.mapping_label=QtWidgets.QLabel();root.addWidget(self.mapping_label)
        row=QtWidgets.QHBoxLayout();root.addLayout(row)
        for key,title,lo,hi in (('exposure_ms','Exposure (ms)',.1,6000),('num_average','Samples / batch',1,65535),('num_repeat','Batches',1,65535),('timeout_s','Timeout / batch (s)',.1,3600)):
            field=QtWidgets.QDoubleSpinBox() if key in ('exposure_ms','timeout_s') else QtWidgets.QSpinBox()
            if isinstance(field,QtWidgets.QDoubleSpinBox):field.setDecimals(1);field.setSingleStep(.1)
            field.setRange(lo,hi);self.fields[key]=field;row.addWidget(QtWidgets.QLabel(title));row.addWidget(field)
        row=QtWidgets.QHBoxLayout();root.addLayout(row);self.config_buttons=[]
        for title,callback in (('변수 불러오기',self.load),('변수 저장',self.save),('다른 이름으로 저장',self.save_as)):
            button=QtWidgets.QPushButton(title);row.addWidget(button);button.clicked.connect(callback);self.config_buttons.append(button)
        self.start_button=QtWidgets.QPushButton('Run '+chamber+' Fluorescence');self.stop_button=QtWidgets.QPushButton('Stop / save partial')
        row.addWidget(self.start_button);row.addWidget(self.stop_button);self.start_button.clicked.connect(self.start);self.stop_button.clicked.connect(self.api.stop_fluorescence)
        row=QtWidgets.QHBoxLayout();root.addLayout(row)
        self.directory=QtWidgets.QLineEdit(str(Path(__file__).resolve().parents[2]/'data/characterization'));row.addWidget(self.directory)
        folder=QtWidgets.QPushButton('결과 저장 폴더');folder.clicked.connect(self.choose_folder);row.addWidget(folder)
        load_result=QtWidgets.QPushButton('이전 결과 열기');load_result.clicked.connect(self.load_result);row.addWidget(load_result)
        self.status=QtWidgets.QLabel('대기 중');self.status.setWordWrap(True);root.addWidget(self.status)
        self.summary=QtWidgets.QLabel();self.summary.setWordWrap(True);root.addWidget(self.summary)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        self.figure=Figure(figsize=(8,9));self.canvas=FigureCanvasQTAgg(self.figure);self.canvas.setMinimumHeight(500);root.addWidget(self.canvas,1)
        root.addWidget(QtWidgets.QLabel('FFT: 원본 코드와 같은 명목상 exposure 간격 사용 · 배치 사이 PC 대기 시간은 제외됩니다.'))
        self.config_valid=False
        try:self.populate(config.load_settings(chamber));self.config_valid=True
        except Exception as exc:self.status.setText(str(exc))
        worker.task_progress.connect(self.progress)
        self.timer=QtCore.QTimer(self);self.timer.setInterval(300);self.timer.timeout.connect(self.controls);self.timer.start();self.controls()

    def populate(self,value):
        for key,field in self.fields.items():field.setValue(value[key])

    def value(self):
        return config.validate_settings(dict(schema_version=1,chamber=self.chamber,**{key:field.value() for key,field in self.fields.items()}))

    def load(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Load fluorescence settings',str(config.ROOT),'JSON (*.json)')
        if path:
            try:self.populate(config.load_settings(self.chamber,path));self.config_valid=True;self.status.setText('불러옴: '+path)
            except Exception as exc:self.status.setText(str(exc))

    def save(self):
        try:
            path=config.ROOT/f'fluorescence_{self.chamber}.local.json';config.save(path,self.value());self.config_valid=True;self.status.setText('저장됨: '+str(path))
        except Exception as exc:self.status.setText(str(exc))

    def save_as(self):
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Save fluorescence settings',str(config.ROOT/f'fluorescence_{self.chamber}.local.json'),'JSON (*.json)')
        if path:
            try:config.save(path,self.value());self.status.setText('저장됨: '+path)
            except Exception as exc:self.status.setText(str(exc))

    def choose_folder(self):
        path=QtWidgets.QFileDialog.getExistingDirectory(self,'Result folder',self.directory.text())
        if path:self.directory.setText(path)

    def start(self):
        try:
            if not self.directory.text().strip():raise ValueError('결과 저장 폴더를 지정하세요.')
            handle=self.api.run_fluorescence(self.chamber,settings=self.value(),directory=self.directory.text())
            self.run_id=handle.request_id;self.rendered_id=None;self.figure.clear();self.canvas.draw_idle();self.summary.setText('수집 중 · 분석은 수집 종료 후 표시됩니다.');self.status.setText('Starting · '+self.run_id)
            if handle.done.is_set() and handle.error:self.status.setText(str(handle.error))
        except Exception as exc:self.status.setText(str(exc))
        self.controls()

    def controls(self):
        runner=self.worker.fluorescence_runner;active=runner.running()
        ready=self.worker.ps is not None and not self.worker.connection_error and not self.worker._closing
        self.start_button.setEnabled(self.config_valid and ready and not active and not self.worker.has_requests() and not self.worker.waveform_runner.running() and not any(t.running() for t in self.worker._background_tasks))
        self.stop_button.setEnabled(active and runner.settings['settings']['chamber']==self.chamber)
        for field in (*self.fields.values(),*self.config_buttons):field.setEnabled(not active)
        try:
            route=config.load_roles()['routes'][self.chamber]
            self.mapping_label.setText(f"EC setup / {self.chamber} experiment · PMT={route['PMT']} · AOM={route['AOM']} (fluorescence에서는 미사용)")
        except Exception as exc:self.mapping_label.setText(str(exc));self.start_button.setEnabled(False)

    def progress(self,label,state):
        if label!='FLUORESCENCE' or state.get('chamber')!=self.chamber:return
        if state.get('run_id')!=self.worker.fluorescence_runner.state.get('run_id'):return
        if self.run_id!=state['run_id']:
            self.figure.clear();self.canvas.draw_idle();self.summary.setText('새 실행 · 수집 중')
        self.run_id=state['run_id']
        self.status.setText(f"{state.get('phase','')} · {state.get('samples',0)}/{state.get('total','?')} samples · {state.get('folder','')}"+(' · '+state['error'] if state.get('error') else ''))
        if state.get('analysis') is not None and self.rendered_id!=self.run_id:
            self.show_result(state['analysis'],state['result']);self.rendered_id=self.run_id

    def show_result(self,data,report):
        draw(self.figure,data);self.canvas.draw_idle();s=report['summary']
        self.summary.setText(f"{report['chamber']} · {report['status']} · N={s['samples']} · mean={s['mean_count']:.5g} · std={s['std_count']:.5g} · FFT peak={s['peak_hz']} Hz")

    def load_result(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Open fluorescence result',self.directory.text(),'Result (result.json)')
        if path:
            try:
                report=config.read(path)
                if report['chamber']!=self.chamber:raise ValueError('Result chamber differs from this tab')
                with np.load(Path(path).parent/'analysis.npz',allow_pickle=False) as archive:data={key:archive[key] for key in archive.files}
                data['summary']=report['summary'];self.show_result(data,report);self.status.setText(str(path))
            except Exception as exc:self.status.setText(str(exc))


class DailyCharacterization(QtWidgets.QTabWidget):
    def __init__(self,worker,bindings,parent=None):
        super().__init__(parent)
        from .workflow_tab import WorkflowTab
        self.workflow=WorkflowTab(bindings,self);self.addTab(self.workflow,'Workflow')
        self.workflow.load_path(str(self.workflow.workflow_root/'daily_fluorescence.py'),check_unsaved=False)
        self.experiments={c:FluorescenceTab(worker,c,self) for c in ('EA','EC')}
        for c,tab in self.experiments.items():self.addTab(tab,c+' Fluorescence')
        self.mapping=MappingTab(worker,self);self.addTab(self.mapping,'FPGA 역할 매핑')
        self.setCurrentWidget(self.experiments['EA'])

    def shutdown(self):
        self.workflow.shutdown()
        for tab in self.experiments.values():tab.timer.stop()

    def still_running(self):return self.workflow.still_running()
