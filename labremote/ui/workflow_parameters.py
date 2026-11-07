"""Queue-only parameter editor. Editing never connects to an instrument."""
import json
from copy import deepcopy
from pathlib import Path
from PyQt5 import QtCore, QtWidgets
from labremote.entanglement import config
from labremote.runtime.workflow_queue import freeze_job, validate_plan


class EntanglementParameters(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout=QtWidgets.QVBoxLayout(self)
        bar=QtWidgets.QHBoxLayout();layout.addLayout(bar)
        self.load_button=QtWidgets.QPushButton('설정 파일 불러오기…')
        self.saved_button=QtWidgets.QPushButton('저장된 실험 설정 불러오기')
        bar.addWidget(self.load_button);bar.addWidget(self.saved_button);bar.addStretch()
        self.info=QtWidgets.QLabel('이 항목에 설정 사본을 저장합니다. 다른 Queue 항목에는 영향을 주지 않습니다.')
        self.info.setWordWrap(True);layout.addWidget(self.info)
        scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);layout.addWidget(scroll,1)
        body=QtWidgets.QWidget();scroll.setWidget(body);grid=QtWidgets.QGridLayout(body)
        groups={}
        for title,row,col in [('장비 · 측정 basis',0,0),('측정 횟수',0,1),('시퀀스 시간',1,0),('검출 · 판정',1,1)]:
            box=QtWidgets.QGroupBox(title);form=QtWidgets.QFormLayout(box);grid.addWidget(box,row,col)
            groups[title]=form
        self.fpga=QtWidgets.QLineEdit('fpga_local');groups['장비 · 측정 basis'].addRow('FPGA 장비',self.fpga)
        self.basis=QtWidgets.QComboBox();self.basis.addItem('ZZ basis','zz');self.basis.addItem('MW detuned','mw_detuned')
        groups['장비 · 측정 basis'].addRow('측정 basis',self.basis)
        self.fields={}
        phase={'detuning_hz','phase_magnitude_deg','pi_ea_us','pi_ec_us'}
        counts={'batches','groups_per_loop','inner_trials','fpga_loops','timeout_s'}
        detection={'decay_lower_a','decay_lower_c','coincidence_half_window_bins','detection_us','threshold_ea','threshold_ec'}
        labels={'phase_magnitude_deg':'위상 크기 (deg)','detuning_hz':'MW detuning (Hz)',
                'pi_ea_us':'EA π 시간 (µs)','pi_ec_us':'EC π 시간 (µs)',
                'batches':'Batches / workflow','groups_per_loop':'Groups / FPGA loop',
                'inner_trials':'Trials / group','fpga_loops':'FPGA loops / batch'}
        for key,label,lo,hi,decimals in config.FIELDS:
            field=QtWidgets.QDoubleSpinBox() if decimals else QtWidgets.QSpinBox()
            if decimals:field.setDecimals(decimals)
            field.setRange(lo,hi);field.setKeyboardTracking(False)
            if key.startswith('pi_'):field.setSingleStep(.02)
            elif key=='mirror_wait_ms':field.setSingleStep(.5)
            elif key=='phase_magnitude_deg':field.setSingleStep(30)
            elif key.endswith('_us'):field.setSingleStep(.01)
            section='장비 · 측정 basis' if key in phase else '측정 횟수' if key in counts else '검출 · 판정' if key in detection else '시퀀스 시간'
            groups[section].addRow(labels.get(key,label),field);self.fields[key]=field
        self.summary=QtWidgets.QLabel();self.summary.setWordWrap(True);layout.addWidget(self.summary)
        self.basis.currentIndexChanged.connect(self.update_summary)
        for field in self.fields.values():field.valueChanged.connect(self.update_summary)
        self.populate({'fpga':'fpga_local','settings':config.defaults()})

    def populate(self,parameters):
        if not isinstance(parameters,dict):raise ValueError('Parameters must be a JSON object')
        settings=config.validate(parameters['settings'])
        name=parameters.get('fpga','fpga_local')
        if not isinstance(name,str) or not name.strip():raise ValueError('FPGA 장비 이름을 입력하세요.')
        self.fpga.setText(name)
        blockers=[QtCore.QSignalBlocker(field) for field in self.fields.values()]
        blockers.append(QtCore.QSignalBlocker(self.basis))
        for key,field in self.fields.items():field.setValue(settings[key])
        self.basis.setCurrentIndex(self.basis.findData(settings['basis']))
        del blockers
        self.update_summary()

    def parameters(self,base,validate=True):
        value=deepcopy(base)
        value['fpga']=self.fpga.text().strip()
        settings=dict(schema_version=1,basis=self.basis.currentData(),
                      **{key:field.value() for key,field in self.fields.items()})
        if validate:
            if not value['fpga']:raise ValueError('FPGA 장비 이름을 입력하세요.')
            settings=config.validate(settings)
        value['settings']=settings
        return value

    def update_summary(self):
        mw=self.basis.currentData()=='mw_detuned'
        for key in ('detuning_hz','phase_magnitude_deg','pi_ea_us','pi_ec_us'):self.fields[key].setEnabled(mw)
        try:
            c=self.parameters({},validate=True)['settings']
            note=f"Workflow 1회 = {c['batches']:,} batches · 최대 {config.nominal_trials(c):,} attempts / batch"
            if mw:
                p=config.phase_values(c)
                note+=f"\n펄스 시작 시간차 {p['start_gap_us']:.2f} µs · 상대 위상 변화 {p['drive_phase_deg']:.3f}°"
            else:note+='\nZZ: 분석 MW 펄스를 사용하지 않습니다.'
            self.summary.setText(note+'\nRF/MW 주파수·출력은 별도 설정합니다. 그룹 반복 N과 batches는 별개입니다.')
        except Exception as exc:self.summary.setText('설정 확인: '+str(exc))


class IonCheckParameters(QtWidgets.QWidget):
    """Queue settings using the same channel choices and validation as IonCheckTab."""
    def __init__(self):
        super().__init__()
        from labremote.ion_check import config as ion
        self.fields={};self.mapping_fields={}
        layout=QtWidgets.QVBoxLayout(self);bar=QtWidgets.QHBoxLayout();layout.addLayout(bar)
        self.load_button=QtWidgets.QPushButton('설정 파일 불러오기…');self.saved_button=QtWidgets.QPushButton('저장된 Ion Check 설정 불러오기')
        bar.addWidget(self.load_button);bar.addWidget(self.saved_button);bar.addStretch()
        self.info=QtWidgets.QLabel('이 Queue 항목에 설정 사본을 저장합니다. Ion Check 탭의 저장 설정은 변경하지 않습니다.');self.info.setWordWrap(True);layout.addWidget(self.info)
        scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);layout.addWidget(scroll)
        body=QtWidgets.QWidget();scroll.setWidget(body);form=QtWidgets.QFormLayout(body)
        self.fpga=QtWidgets.QLineEdit('fpga_local');form.addRow('FPGA 장비',self.fpga)
        for key,label in [('pmt_1','PMT 입력 1'),('pmt_2','PMT 입력 2'),('laser_a','Laser A (EA)'),('laser_b','Laser B (170)'),('laser_c','Laser C (EC)')]:
            box=QtWidgets.QComboBox()
            if key=='pmt_2':box.addItem('사용 안 함 · 입력 1만 측정',None)
            for name in (ion.PMT_CHOICES if key.startswith('pmt') else ion.LASER_CHOICES):box.addItem(name,name)
            self.mapping_fields[key]=box;form.addRow(label,box)
        for key,label,lo,hi in [('exposure_us','노출 시간 (µs)',1,10000),('settle_us','안정화 대기 (µs)',1,10000),('threshold_a','Laser A threshold',0,65535),('threshold_b','Laser B threshold',0,65535),('threshold_c','Laser C threshold',0,65535),('max_attempts','최대 측정 횟수 N (최초 포함)',1,10000),('retry_delay_s','재측정 간격 (s)',0,3600),('timeout_s','측정 timeout (s)',.1,600)]:
            box=QtWidgets.QDoubleSpinBox() if key.endswith('_s') else QtWidgets.QSpinBox();box.setRange(lo,hi);box.setKeyboardTracking(False)
            if key.endswith('_s'):box.setDecimals(2);box.setSingleStep(.1)
            if key.startswith('threshold'):box.setSpecialValueText('미설정')
            self.fields[key]=box;form.addRow(label,box)
        note=QtWidgets.QLabel('두 PMT 선택 시 count를 합산합니다. 밝음: count ≥ threshold.\n정상 확인 시 즉시 종료합니다. DAC swap 없이 재측정만 수행합니다.\n종료 상태: 선택한 A/C 및 7GA/7GC ON, B OFF.');note.setWordWrap(True);form.addRow(note)
        self.populate({'settings':ion.defaults()})

    def populate(self,parameters):
        from labremote.ion_check import config as ion
        c=ion.validate(parameters['settings']);name=parameters.get('fpga','fpga_local')
        if not isinstance(name,str) or not name.strip():raise ValueError('FPGA 장비 이름을 입력하세요.')
        self.fpga.setText(name)
        for key,box in self.fields.items():box.setValue(c[key] if c[key] is not None else 0)
        for key,box in self.mapping_fields.items():box.setCurrentIndex(box.findData(c['mapping'][key]))

    def parameters(self,base,validate=True):
        from labremote.ion_check import config as ion
        value=deepcopy(base);value['fpga']=self.fpga.text().strip()
        c=dict(schema_version=2,mapping={k:b.currentData() for k,b in self.mapping_fields.items()},**{k:b.value() for k,b in self.fields.items()})
        for k in ('threshold_a','threshold_b','threshold_c'):
            if c[k]==0:c[k]=None
        if validate:
            if not value['fpga']:raise ValueError('FPGA 장비 이름을 입력하세요.')
            c=ion.validate(c,require_thresholds=True)
        value['settings']=c;return value


class MonitorSettings(QtWidgets.QWidget):
    def __init__(self,job):
        super().__init__()
        from labremote.runtime.monitor_config import settings
        value=settings(job);form=QtWidgets.QFormLayout(self)
        self.kind=QtWidgets.QComboBox()
        for label,key in [('없음','none'),('Ion Check','ion'),('SPAM','spam'),('RE','ent')]:self.kind.addItem(label,key)
        self.kind.setCurrentIndex(self.kind.findData(value['kind']))
        self.title=QtWidgets.QLineEdit(value['title']);self.title.setPlaceholderText('비워 두면 Workflow 이름 사용')
        self.view=QtWidgets.QComboBox();self.view.addItem('그룹 누적','cumulative');self.view.addItem('최신 회차','latest')
        self.view.setCurrentIndex(self.view.findData(value['view']))
        form.addRow('모니터 종류',self.kind);form.addRow('탭 이름',self.title);form.addRow('기본 표시',self.view)
        note=QtWidgets.QLabel('Queue 항목별로 독립된 탭을 만듭니다. 선택한 그룹 안에서 누적하며, 서로 다른 RE 설정은 분리합니다. 모니터 설정은 실험 실행 조건을 바꾸지 않습니다.')
        note.setWordWrap(True);form.addRow(note)

    def value(self):
        from labremote.runtime.monitor_config import validate
        return validate(dict(kind=self.kind.currentData(),title=self.title.text().strip(),view=self.view.currentData()))


class WorkflowJobDialog(QtWidgets.QDialog):
    def __init__(self,job,parent=None,*,bindings_provider=None):
        super().__init__(parent)
        self.job=deepcopy(job);self.base=deepcopy(job['parameters']);self.previous_tab=0
        migration_note=''
        if Path(job['filename']).name in ('re_setup.py','spam_setup.py'):
            from labremote.runtime.setup_workflow import migrate_legacy
            self.base=migrate_legacy(Path(job['filename']).name,self.base)
            replacement=freeze_job(Path(__file__).resolve().parents[1]/'workflow/setup.py')
            self.job.update(filename=replacement['filename'],source=replacement['source'],sha256=replacement['sha256'])
            job=self.job
            migration_note='기존 설정을 범용 setup으로 변환했습니다. 적용하면 같은 이름의 Queue 항목에 저장합니다. 취소하면 변경하지 않습니다.'
        from labremote.runtime.workflow_ui import editor_kind
        kind=editor_kind(job['source'])
        # Compatibility for frozen Queue sources created before declarations existed.
        if kind is None:
            kind={'queue_entanglement.py':'entanglement','re.py':'entanglement','ion_checks.py':'ion','ion_check.py':'ion','spam.py':'spam'}.get(Path(job['filename']).name)
        profile_error=''
        self.setWindowTitle('Workflow 설정');self.resize(1000,860)
        layout=QtWidgets.QVBoxLayout(self);form=QtWidgets.QFormLayout();layout.addLayout(form)
        self.name=QtWidgets.QLineEdit(job['name']);self.repeat=QtWidgets.QSpinBox();self.repeat.setRange(1,10000);self.repeat.setValue(job['repeat'])
        self.policy=QtWidgets.QComboBox();self.policy.addItems(['stop','skip']);self.policy.setCurrentText(job['on_failure'])
        form.addRow('이름',self.name);form.addRow('반복',self.repeat);form.addRow('실패 시',self.policy)
        filename=QtWidgets.QLabel(job['filename']);filename.setWordWrap(True);form.addRow('Workflow',filename)
        self.tabs=QtWidgets.QTabWidget();layout.addWidget(self.tabs,1)
        if migration_note:
            notice=QtWidgets.QLabel(migration_note);notice.setWordWrap(True);layout.insertWidget(1,notice)
        self.editor=None;self.settings_config=config;self.settings_filename='entanglement.local.json'
        if kind=='setup':
            from .setup_parameters import SetupParameters
            self.editor=SetupParameters(bindings_provider);self.tabs.addTab(self.editor,'장비 · 파라미터 설정')
            if not self.base:self.base=self.editor.defaults()
        elif kind=='entanglement':
            self.editor=EntanglementParameters();self.tabs.addTab(self.editor,'얽힘 설정 · devices.parameters')
            load_bar=QtWidgets.QHBoxLayout()
            load_bar.addWidget(self.editor.load_button);load_bar.addWidget(self.editor.saved_button);load_bar.addStretch()
            layout.insertLayout(1,load_bar)
        elif kind=='ion':
            from labremote.ion_check import config as ion
            self.settings_config=ion;self.settings_filename='ion_check.local.json'
            self.editor=IonCheckParameters();self.tabs.addTab(self.editor,'Ion Check 설정 · devices.parameters')
        elif kind=='spam':
            from .spam_parameters import SpamParameters
            self.editor=SpamParameters();self.tabs.addTab(self.editor,'SPAM 설정 · devices.parameters')
        if not self.base:
            try:
                if kind in ('entanglement','ion'):self.base={'fpga':'fpga_local','settings':self.settings_config.load()}
                elif kind=='spam':
                    self.base=self.editor.defaults()
            except Exception as exc:profile_error=str(exc)
        self.json=QtWidgets.QPlainTextEdit();self.json.setPlainText(json.dumps(self.base,ensure_ascii=False,indent=2))
        self.json_index=self.tabs.addTab(self.json,'JSON · 고급 편집') if kind!='setup' else -1
        if kind=='setup':self.json.setParent(self);self.json.hide()
        self.monitor=MonitorSettings(job);self.monitor_index=self.tabs.addTab(self.monitor,'Monitor')
        self.reload=QtWidgets.QCheckBox('Python 소스를 현재 파일에서 다시 가져오기');layout.addWidget(self.reload)
        self.error=QtWidgets.QLabel();self.error.setWordWrap(True);self.error.setStyleSheet('color: #b42318');layout.addWidget(self.error)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('적용');buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText('취소')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        if self.editor is not None:
            try:
                if not self.base:
                    self.base=self.editor.defaults() if kind=='spam' else {'fpga':'fpga_local','settings':self.settings_config.load()}
                    self.json.setPlainText(json.dumps(self.base,ensure_ascii=False,indent=2))
                self.editor.populate(self.base)
            except Exception as exc:
                self.tabs.setCurrentIndex(self.json_index);self.previous_tab=self.json_index
                self.error.setText('기존 설정을 확인하거나 설정 파일을 불러오세요: '+str(exc))
            if hasattr(self.editor,'load_button'):
                self.editor.load_button.clicked.connect(self.load_file)
                self.editor.saved_button.clicked.connect(lambda:self.load_settings(None))
        self.tabs.currentChanged.connect(self.switch_tab)
        if profile_error:self.error.setText('저장된 측정 설정을 확인하세요: '+profile_error)

    def read_json(self):
        value=json.loads(self.json.toPlainText())
        if not isinstance(value,dict):raise ValueError('Parameters must be a JSON object')
        json.dumps(value,allow_nan=False)
        return value

    def switch_tab(self,index):
        if self.editor is None:return
        try:
            if self.previous_tab==0 and index!=0:
                self.base=self.editor.parameters(self.base,validate=False)
                self.json.setPlainText(json.dumps(self.base,ensure_ascii=False,indent=2))
            elif self.previous_tab==self.json_index:
                value=self.read_json();self.editor.populate(value);self.base=value
            self.previous_tab=index;self.error.clear()
        except Exception as exc:
            with QtCore.QSignalBlocker(self.tabs):self.tabs.setCurrentIndex(self.previous_tab)
            self.error.setText(str(exc))

    def load_file(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'실험 설정 불러오기',str(self.settings_config.ROOT),'JSON (*.json)')
        if path:self.load_settings(path)

    def load_settings(self,path):
        try:
            settings=self.settings_config.load(path)
            base=self.read_json() if self.tabs.currentIndex()==self.json_index else self.editor.parameters(self.base,validate=False)
            base['settings']=settings;base.setdefault('fpga','fpga_local')
            self.editor.populate(base);self.base=base
            self.json.setPlainText(json.dumps(base,ensure_ascii=False,indent=2))
            origin=path or self.settings_config.ROOT/self.settings_filename
            self.editor.info.setText('불러온 설정: '+str(origin) if Path(origin).exists() else '프로젝트 기본 설정을 불러왔습니다. 저장된 실험 설정 파일은 없습니다.')
            self.error.clear()
        except Exception as exc:self.error.setText(str(exc))

    def accept(self):
        try:
            parameters=self.read_json() if self.editor is None or self.tabs.currentIndex()==self.json_index else self.editor.parameters(self.base)
            if self.editor is not None:
                from .setup_parameters import SetupParameters
                from .spam_parameters import SpamParameters
                if isinstance(self.editor,SetupParameters):
                    from labremote.runtime.setup_workflow import validate
                    validate(parameters)
                elif isinstance(self.editor,SpamParameters):self.editor.validate_parameters(parameters)
                else:
                    if isinstance(self.editor,IonCheckParameters):self.settings_config.validate(parameters['settings'],require_thresholds=True)
                    else:self.settings_config.validate(parameters['settings'])
                    if not isinstance(parameters.get('fpga'),str) or not parameters['fpga'].strip():raise ValueError('FPGA 장비 이름을 입력하세요.')
            job=deepcopy(self.job)
            if self.reload.isChecked():
                fresh=freeze_job(job['filename']);job.update(source=fresh['source'],sha256=fresh['sha256'])
            job['monitor']=self.monitor.value()
            job.update(name=self.name.text().strip(),repeat=self.repeat.value(),on_failure=self.policy.currentText(),parameters=parameters)
            validate_plan(dict(schema_version=1,repeat=1,jobs=[job]));self.job=job
        except Exception as exc:self.error.setText(str(exc));return
        super().accept()
