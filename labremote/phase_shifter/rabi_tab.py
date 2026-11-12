"""Phase/time Rabi scan setup and live plots."""
import json
from pathlib import Path
import numpy as np
from PyQt5 import QtCore, QtWidgets as W
from labremote.devices.fpga.mapping import bound_methods
from labremote.data_paths import tab_data_directory
from . import config, rabi
from .selectors import PhaseShifterEtcTab
from .calibration import CalibrationSelector


@bound_methods(None)
class PhaseRabiTab(W.QWidget):
    def __init__(self,worker,parent=None):
        super().__init__(parent);self.worker=worker;self.runner=worker.phase_rabi_runner
        self.fields={};self.run_id=None;self.points=[];self.fits=[];self.phases=[];self.times=[]
        root=W.QVBoxLayout(self)
        root.addWidget(W.QLabel('위상별 Rabi · 위상 설정 → 안정화 → [냉각·초기화 → 가변 길이 MW 펄스 → 검출] 반복'))
        split=W.QSplitter();root.addWidget(split,1)
        scroll=W.QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumWidth(410);split.addWidget(scroll)
        self.settings_panel=W.QWidget();scroll.setWidget(self.settings_panel);left=W.QVBoxLayout(self.settings_panel)
        self.calibration=CalibrationSelector();left.addWidget(self.calibration)
        self.calibration.changed.connect(self.controls)
        phase=self.group(left,'위상 설정')
        for key,title,lo,hi,dec in [('scan_start_deg','시작 위상 (°)',0,360,6),('scan_stop_deg','끝 위상 (°)',0,360,6),('scan_step_deg','위상 간격 (°)',.000001,360,6)]:
            self.field(phase,key,title,lo,hi,dec)
        self.field(phase,'phase_settle_clocks','위상 안정화 (µs)',.03,655.38,2,100)
        pulse=self.group(left,'Rabi 펄스 스캔')
        for key,title,lo in [('pulse_start_us','시작 시간 (µs)',0),('pulse_stop_us','끝 시간 (µs)',0),('pulse_step_us','시간 간격 (µs)',.01)]:
            self.field(pulse,key,title,lo,655.38,2)
        self.field(pulse,'N_average','지점당 반복 횟수',1,65535,0)
        self.summary=W.QLabel();self.summary.setWordWrap(True);left.addWidget(self.summary)
        self.skip=W.QCheckBox('기존 CSV에서 보정 불가 각도 제외');self.skip.setChecked(True);left.addWidget(self.skip);self.skip.toggled.connect(self.controls)
        self.mapping=PhaseShifterEtcTab(config.hd)
        group=W.QGroupBox('이 실험의 FPGA 역할 매핑');group.setCheckable(True);group.setChecked(False)
        layout=W.QVBoxLayout(group);layout.addWidget(self.mapping);self.mapping.hide();group.toggled.connect(self.mapping.setVisible);left.addWidget(group)
        self.mapping.selection_changed.connect(self.controls)
        advanced=W.QGroupBox('냉각 · 초기화 · 검출');advanced.setCheckable(True);advanced.setChecked(False);left.addWidget(advanced)
        body=W.QWidget();W.QVBoxLayout(advanced).addWidget(body);form=W.QFormLayout(body);body.hide();advanced.toggled.connect(body.setVisible)
        for key,title in [('T_cool','냉각 시간'),('T_init','초기화 시간'),('T_det','검출 시간'),('T_wait_for_aom_off','AOM OFF 대기')]:
            self.field(form,key,title+' (µs)',0,655.35,2,100)
        for key,title in [('T_cool_repeat','냉각 반복'),('T_det_repeat','검출 반복')]:self.field(form,key,title,1,65535,0)
        self.field(form,'threshold','Bright 기준 (counts ≥)',0,65535,0)
        self.field(form,'timeout_s','지점당 Timeout (s)',.1,600,1)
        for title,fn in [('설정 불러오기',self.load),('설정 저장',self.save)]:
            b=W.QPushButton(title);b.clicked.connect(fn);left.addWidget(b)
        left.addStretch()
        right_widget=W.QWidget();right=W.QVBoxLayout(right_widget);split.addWidget(right_widget);split.setSizes([430,850])
        self.directory=W.QLineEdit(str(tab_data_directory(None,'phase_rabi')))
        folder_row=W.QHBoxLayout();right.addLayout(folder_row);folder_row.addWidget(self.directory)
        self.folder_button=W.QPushButton('저장 폴더');folder_row.addWidget(self.folder_button);self.folder_button.clicked.connect(self.choose_folder)
        buttons=W.QHBoxLayout();right.addLayout(buttons)
        self.validate_button=W.QPushButton('시퀀스 검증');self.start_button=W.QPushButton('위상별 Rabi 시작');self.stop_button=W.QPushButton('중지 · 부분 저장')
        for b,fn in [(self.validate_button,self.validate_sequence),(self.start_button,self.start),(self.stop_button,self.runner.cancel)]:buttons.addWidget(b);b.clicked.connect(fn)
        self.status=W.QLabel('대기 중 · 실제 측정 없음');self.status.setWordWrap(True);right.addWidget(self.status)
        self.progress_bar=W.QProgressBar();right.addWidget(self.progress_bar)
        row=W.QHBoxLayout();right.addLayout(row);row.addWidget(W.QLabel('선택한 위상'))
        self.selected_phase=W.QComboBox();row.addWidget(self.selected_phase);self.selected_phase.currentIndexChanged.connect(self.draw)
        self.result_button=W.QPushButton('저장된 결과 열기');self.result_button.clicked.connect(self.open_result);row.addWidget(self.result_button)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        self.figure=Figure(figsize=(9,7),constrained_layout=True);self.canvas=FigureCanvasQTAgg(self.figure);right.addWidget(self.canvas,1)
        worker.task_progress.connect(self.progress)
        self.timer=QtCore.QTimer(self);self.timer.setInterval(400);self.timer.timeout.connect(self.controls);self.timer.start()
        self.draw();self.controls()

    @staticmethod
    def group(layout,title):
        box=W.QGroupBox(title);layout.addWidget(box);return W.QFormLayout(box)

    def field(self,form,key,title,lo,hi,dec,scale=1):
        box=W.QDoubleSpinBox() if dec else W.QSpinBox()
        if dec:box.setDecimals(dec)
        box.setRange(lo,hi);box.setValue(rabi.DEFAULTS[key]/scale if dec else int(rabi.DEFAULTS[key]));box.setProperty('scale',scale)
        self.fields[key]=box;form.addRow(title,box);box.valueChanged.connect(self.controls)

    def value(self):
        c=dict(rabi.DEFAULTS)
        for k,b in self.fields.items():
            v=b.value()*b.property('scale');c[k]=round(v) if b.property('scale')==100 or isinstance(b,W.QSpinBox) else v
        c['calibration']=self.calibration.active();c['skip_unreliable']=self.skip.isChecked()
        return self.mapping.apply_to(c)

    def controls(self,*_):
        if not hasattr(self,'start_button'):return
        error=''
        try:
            c=dict(rabi.DEFAULTS)
            for k in ('scan_start_deg','scan_stop_deg','scan_step_deg','pulse_start_us','pulse_stop_us','pulse_step_us'):c[k]=self.fields[k].value()
            c.update(calibration=self.calibration.active(),skip_unreliable=self.skip.isChecked())
            skipped=[];phases=config.scan_points(c,skipped);times=rabi.times(c)
            text=f'{len(phases)}개 위상 × {len(times)}개 시간 × {self.fields["N_average"].value()} shots'
            if skipped:text+='\n제외 각도: '+', '.join(str(p['angle_deg']) for p in skipped)
            self.summary.setText(text)
            self.mapping.selection()
        except (ValueError,KeyError) as exc:error=str(exc);self.summary.setText(error)
        active=self.runner.running()
        busy=self.worker.has_requests() or self.worker.waveform_runner.running() or any(t.running() for t in self.worker._background_tasks)
        ready=self.worker.ps is not None and not self.worker.connection_error and not self.worker._closing
        self.start_button.setEnabled(ready and not busy and not active and not error)
        self.stop_button.setEnabled(active);self.settings_panel.setEnabled(not active);self.directory.setEnabled(not active);self.validate_button.setEnabled(not active)
        self.folder_button.setEnabled(not active);self.result_button.setEnabled(not active)

    def choose_folder(self):
        path=W.QFileDialog.getExistingDirectory(self,'결과 저장 폴더',self.directory.text())
        if path:self.directory.setText(path)

    def populate(self,c):
        c,_,_,_=rabi.validate(c)
        self.calibration.set_table(c.get('calibration'));self.skip.setChecked(c.get('skip_unreliable',True))
        for k,b in self.fields.items():b.setValue(c[k]/b.property('scale') if isinstance(b,W.QDoubleSpinBox) else int(c[k]))
        for role,box in self.mapping.output_selectors.items():box.setCurrentIndex(box.findData(c['outputs'][role]))
        for box,name in zip(self.mapping.phase_selectors,c['phase_outputs']):box.setCurrentIndex(box.findData(name))
        box=self.mapping.detector_selector;box.setCurrentIndex(box.findData(c['detector_nickname']));self.controls()

    def validate_sequence(self):
        try:rabi.validate(self.value());self.status.setText('검증 통과 · 매핑, 펄스 범위, 시퀀스 확인')
        except Exception as exc:self.status.setText(str(exc))

    def save(self):
        try:
            c,*_=rabi.validate(self.value());path,_=W.QFileDialog.getSaveFileName(self,'설정 저장','phase_rabi.json','JSON (*.json)')
            if path:Path(path).write_text(json.dumps(c,ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception as exc:self.status.setText(str(exc))

    def load(self):
        path,_=W.QFileDialog.getOpenFileName(self,'설정 불러오기','','JSON (*.json)')
        if path:
            try:self.populate(json.loads(Path(path).read_text(encoding='utf-8-sig')))
            except Exception as exc:self.status.setText(str(exc))

    def start(self):
        try:
            if not self.directory.text().strip():raise ValueError('결과 저장 폴더를 입력하세요.')
            handle=self.runner.start(self.value(),directory=self.directory.text());self.run_id=handle.request_id
            self.points=[];self.fits=[];self.status.setText(str(handle.error) if handle.done.is_set() and handle.error else '측정 시작')
        except Exception as exc:self.status.setText(str(exc))
        self.controls()

    def progress(self,label,state):
        if label!=self.runner.label or state.get('run_id')!=self.run_id:return
        self.phases=state.get('phases',self.phases);self.times=state.get('times',self.times)
        self.points=state.get('points',self.points);self.fits=state.get('fits',self.fits)
        self.progress_bar.setRange(0,state.get('total',len(self.phases)*len(self.times)));self.progress_bar.setValue(len(self.points))
        self.status.setText(' · '.join(str(state[k]) for k in ('phase','error','folder') if state.get(k)))
        self.refresh_phases();self.draw();self.controls()

    def refresh_phases(self):
        if self.selected_phase.count()!=len(self.phases):
            with QtCore.QSignalBlocker(self.selected_phase):
                self.selected_phase.clear()
                for p in self.phases:self.selected_phase.addItem(f'{p["requested_angle_deg"]:g}° · code {p["code"]}')

    def draw(self,*_):
        if not hasattr(self,'figure'):return
        self.figure.clear();grid=self.figure.add_gridspec(2,2);heat=self.figure.add_subplot(grid[0,:]);osc=self.figure.add_subplot(grid[1,0]);freq=self.figure.add_subplot(grid[1,1])
        heat.set(xlabel='Pulse time (µs)',ylabel='Requested phase (°)',title='Phase-resolved Rabi · P(bright)')
        osc.set(xlabel='Pulse time (µs)',ylabel='P(bright)',ylim=(-.05,1.05));freq.set(xlabel='Requested phase (°)',ylabel='Rabi frequency (kHz)')
        if self.phases and self.times:
            z=np.full((len(self.phases),len(self.times)),np.nan)
            for p in self.points:z[p['phase_index'],p['time_index']]=p['probability']
            x=np.array(self.times)/100;y=[p['requested_angle_deg'] for p in self.phases]
            mesh=heat.pcolormesh(x,y,z,shading='nearest',vmin=0,vmax=1,cmap='viridis');self.figure.colorbar(mesh,ax=heat,label='P(bright)')
            i=max(0,self.selected_phase.currentIndex());data=[p for p in self.points if p['phase_index']==i]
            if data:
                osc.errorbar([p['pulse_clocks']/100 for p in data],[p['probability'] for p in data],
                    yerr=[np.sqrt(p['probability']*(1-p['probability'])/p['shots']) for p in data],fmt='.',label='Measured')
                fit=next((f for f in self.fits if f['phase_index']==i),None)
                if fit and fit['valid']:
                    t=np.linspace(x[0],x[-1],500);osc.plot(t,rabi.model(t,*fit['parameters']),label='Damped fit');osc.set_title(f'{y[i]:g}° · {fit["frequency_khz"]:.3f} kHz')
                elif fit:osc.set_title(fit['reason'])
                osc.legend(fontsize=8)
            good=[f for f in self.fits if f['valid']]
            if good:freq.errorbar([f['requested_angle_deg'] for f in good],[f['frequency_khz'] for f in good],yerr=[f['error_khz'] for f in good],fmt='o-')
            bad=sum(not f['valid'] for f in self.fits)
            freq.set_title(f'Independent fits · {bad} invalid')
        for a in (osc,freq):a.grid(alpha=.2)
        self.canvas.draw_idle()

    def open_result(self):
        path,_=W.QFileDialog.getOpenFileName(self,'결과 열기',self.directory.text(),'Result (result.json)')
        if path:
            try:
                v=json.loads(Path(path).read_text(encoding='utf-8'))
                if v.get('experiment')!='phase_rabi':raise ValueError('위상별 Rabi 결과를 선택하세요.')
                self.phases=v['phases'];self.times=v['pulse_clocks'];self.points=v['points'];self.fits=v['fits'];self.refresh_phases();self.draw();self.status.setText(v['status']+' · '+path)
            except Exception as exc:self.status.setText(str(exc))

    def shutdown(self):
        self.timer.stop()
        if self.runner.running():self.runner.cancel()
