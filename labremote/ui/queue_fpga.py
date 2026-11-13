"""Queue-local FPGA routing editor. Never writes a worker or a config file."""
from copy import deepcopy
import json
from PyQt5 import QtCore, QtWidgets as W
from labremote.devices.fpga.mapping import PINS, DEFAULT_ROLES, EXPERIMENTS, Profile, capability, compatible


KINDS = {'MotorScanTab':'scan','FluorescenceTab':'fluorescence','RabiTab':'rabi','DecayExperimentTab':'decay',
         'HOMTab':'hom','EntanglementTab':'entanglement','IonCheckTab':'ion_check',
         'MicromotionPage':'micromotion','PhaseShifterTab':'phase_shifter','PhaseHoldTab':'phase_shifter','PhaseRabiTab':'phase_shifter','HalfPiRamseyTab':'phase_shifter'}
ROLE_LABELS = {'PMT':'검출 입력 (PMT)','AOM':'광 제어 (AOM)','MW':'마이크로파 (MW)',
               'EOM_7G_1':'EOM 7G-1','EOM_7G_2':'EOM 7G-2','EOM_2G':'EOM 2G',
               'TRIGGER':'트리거 입력','DETECTOR':'검출 입력','COUNTER':'추가 Counter 입력'}
ION_CHANNELS={'pmt_1':('ION_PMT1','PMTA','검출 입력 1'),'pmt_2':('ION_PMT2','PMTC','검출 입력 2'),
              'laser_a':('ION_A','AOMA','Laser A (EA)'),'laser_b':('ION_B','AOMB','Laser B (170)'),
              'laser_c':('ION_C','AOMC','Laser C (EC)')}
ROLE_LABELS.update({role:title for role,_,title in ION_CHANNELS.values()})
ION_FIXED=('EOM_7GA1','EOM_7GA2','EOM_7GC1','EOM_7GC2','EOM_2GA','EOM_2GC','MW_A','MW_C')


class QueueFPGASettings(W.QWidget):
    changed=QtCore.pyqtSignal()

    def __init__(self, job, target, bindings_provider, kind=None):
        super().__init__()
        self.job=deepcopy(job);self.target=target;self.provider=bindings_provider
        self.parameters=deepcopy(job['parameters']);self.kind=kind
        self.documents=deepcopy(job.get('fpga_profiles',{}));self.overrides={}
        self.rows={};self._loading=False
        root=W.QVBoxLayout(self)
        box=W.QGroupBox('실행 FPGA');root.addWidget(box);layout=W.QVBoxLayout(box)
        row=self.target_row=W.QHBoxLayout();layout.addLayout(row);row.addWidget(target,2)
        self.status=W.QLabel();row.addWidget(self.status,1)
        self.reset=W.QPushButton('FPGA 기본 매핑 불러오기');row.addWidget(self.reset)
        layout.addWidget(W.QLabel('이 Queue 항목은 선택한 FPGA 한 대를 사용합니다.'))
        self.experiment=W.QComboBox()
        for name in EXPERIMENTS:self.experiment.addItem(name,name)
        self.experiment.currentIndexChanged.connect(self.rebuild)
        self.experiment_label=W.QLabel('사용자 Workflow의 실험별 역할 매핑')
        layout.addWidget(self.experiment_label);layout.addWidget(self.experiment)
        scroll=W.QScrollArea();scroll.setWidgetResizable(True);root.addWidget(scroll,1)
        body=W.QWidget();scroll.setWidget(body);body_layout=W.QVBoxLayout(body)
        self.inputs=self.table(body_layout,'입력 핀')
        self.outputs=self.table(body_layout,'출력 핀')
        body_layout.addStretch()
        note=W.QLabel('변경한 매핑은 이 Queue 항목에만 저장됩니다.\nFPGA 공통 핀 이름과 다른 실험의 설정은 변경하지 않습니다.\n입력·출력 방향 및 펌웨어 기능에 맞는 핀을 선택합니다.')
        note.setWordWrap(True);note.setStyleSheet('background:#e8f2fc; padding:12px;');root.addWidget(note)
        self.preview=W.QPlainTextEdit(self);self.preview.setReadOnly(True);self.preview.hide()
        target.currentIndexChanged.connect(self.select_device);self.reset.clicked.connect(self.load_defaults)
        self.select_device()

    @staticmethod
    def table(layout,title):
        group=W.QGroupBox(title);layout.addWidget(group);form=W.QVBoxLayout(group)
        table=W.QTableWidget(0,3);table.setHorizontalHeaderLabels(['실험에서의 역할','FPGA 핀 선택','기능'])
        table.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0,W.QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1,W.QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2,W.QHeaderView.ResizeToContents)
        table.verticalHeader().hide();form.addWidget(table);return table

    def worker(self):
        if self.provider is None:return None
        return next((b.worker for f,b in self.provider().values() if f=='fpga' and b.worker.name==self.target.currentData()
                     and b.worker.ps is not None and not b.worker.connection_error and not b.worker._closing),None)

    def select_device(self,*_):
        name=self.target.currentData();worker=self.worker()
        first_selection=name not in self.documents
        if name and name not in self.documents and worker is not None:
            self.documents[name]=worker.profile.document()
        self.status.setText('● 연결됨' if worker is not None else '연결 끊김 · 저장된 매핑 편집' if name in self.documents else 'FPGA를 선택하세요.')
        self.status.setStyleSheet('color:#238636' if worker is not None else 'color:#616161')
        self.reset.setEnabled(worker is not None)
        from labremote.runtime.workflow_queue import target_fpga
        original=target_fpga(self.job)
        if first_selection and worker is not None and original and name!=original:
            self.load_defaults()
        self.rebuild();self.changed.emit()

    def experiment_name(self):
        p=self.parameters
        if p.get('kind')=='PulseExperimentTab':return p.get('experiment_kind','ramsey')
        return KINDS.get(p.get('kind')) or {'ion':'ion_check','spam':'spam','entanglement':'entanglement','phase_hold':'phase_shifter','setup':'setup'}.get(self.kind)

    def set_parameters(self,parameters):
        self.parameters=deepcopy(parameters);self.rebuild()

    def load_defaults(self,*_):
        worker=self.worker()
        if worker is None:return
        name=self.target.currentData();self.documents[name]=worker.profile.document();self.overrides[name]={}
        # A direct route is initialized from the experiment's default logical role,
        # resolved through the selected board's stored experiment mapping.
        for path,role,experiment,token in self.direct_routes():
            if experiment not in ('fluorescence','rabi','ramsey','initialization','spam'):
                if experiment=='ion_check':
                    from labremote.ion_check.config import default_mapping
                    token=default_mapping()[path[-1]]
                if experiment=='micromotion':
                    from labremote.micromotion.config import defaults
                    token=defaults(self.parameters['settings'].get('chamber','EC'))[path[-1]]
                self.overrides[name][path]=self.resolve(token,experiment,self.documents[name])
                continue
            from labremote.characterization import rabi
            chamber='EC' if 'EC' in path else self.parameters.get('experiment_chamber','EA')
            settings=self.parameters.get('settings',{})
            if isinstance(settings,dict):chamber=settings.get('chamber',chamber)
            defaults=rabi.defaults(chamber)['roles']
            if experiment=='fluorescence':defaults={'PMT':'PMTFA' if chamber=='EA' else 'PMTFC','AOM':'AOMA' if chamber=='EA' else 'AOMC'}
            pin=self.resolve(defaults.get(role,token),experiment,self.documents[name])
            self.overrides[name][path]=pin
        self.rebuild();self.changed.emit()

    def direct_routes(self):
        p=self.parameters;settings=p.get('settings',{});experiment=self.experiment_name()
        if not isinstance(settings,dict):return []
        result=[]
        if experiment=='ion_check':
            from labremote.ion_check.config import default_mapping
            channels=settings.get('mapping',default_mapping())
            return [(('settings','mapping',key),role,experiment,channels.get(key) or '')
                    for key,(role,_,_) in ION_CHANNELS.items()]
        if experiment=='scan':
            from labremote.devices.fpga.mapping import physical
            pin=next((pin for pin in PINS if getattr(physical,pin+'_counter_result',None)==settings.get('pmt')),None)
            return [(('settings','pmt'),'PMT',experiment,pin)]
        if experiment=='micromotion':
            return [(('settings',key),role,experiment,settings.get(key,'')) for key,role in
                    (('trg_pin','TRIGGER'),('pmt_pin','DETECTOR'),('counter_pin','COUNTER'))]
        if experiment=='phase_shifter':
            result=[(('settings','phase_outputs',i),'PHASE D'+str(i),experiment,token)
                    for i,token in enumerate(settings.get('phase_outputs',[]))]
            result.extend((('settings','outputs',role),role,experiment,token) for role,token in settings.get('outputs',{}).items())
            if 'detector_nickname' in settings:result.append((('settings','detector_nickname'),'PMT',experiment,settings['detector_nickname']))
            return result
        groups=[(('settings',),settings)]
        if self.kind=='spam' and set(settings)=={'EA','EC'}:
            groups=[(('settings',ch),settings[ch]) for ch in ('EA','EC')]
        for prefix,c in groups:
            roles=c.get('roles') if isinstance(c,dict) else None
            if experiment in ('fluorescence','rabi','initialization','ramsey','spam') and isinstance(roles,dict):
                result.extend((prefix+('roles',role),role,experiment,token) for role,token in roles.items())
        return result

    @staticmethod
    def resolve(token,experiment,document):
        if token=='':return ''
        if token in PINS:return token
        if experiment=='phase_shifter':return next((p for p,n in document['pins'].items() if n==token),None)
        roles={**DEFAULT_ROLES,**document['experiments'].get(experiment,{})}
        return roles.get(token,next((p for p,n in document['pins'].items() if n==token),None))

    def rebuild(self,*_):
        if self._loading:return
        self._loading=True
        try:
            self.rows={};self.inputs.setRowCount(0);self.outputs.setRowCount(0)
            name=self.target.currentData();document=self.documents.get(name)
            experiment=self.experiment_name()
            self.experiment.setVisible(experiment is None);self.experiment_label.setVisible(experiment is None)
            if experiment=='setup':
                self.experiment.hide();self.experiment_label.hide();self.reset.hide()
                self.inputs.parentWidget().hide();self.outputs.parentWidget().hide()
                self.status.setText('Setup의 FPGA 출력은 실험 조건의 장비·파라미터 행에서 지정합니다.')
                self.update_preview();return
            if document is None:
                self.preview.setPlainText('FPGA 및 매핑 미지정');return
            direct=self.direct_routes()
            if direct:
                for path,role,exp,token in direct:
                    pin=self.overrides.get(name,{}).get(path,self.resolve(token,exp,document))
                    title=(' / '.join(path[1:-2])+' · ' if len(path)>3 else '')+ROLE_LABELS.get(role,role)
                    self.add_row(path,title,pin,exp,role,document,direct=True)
                if experiment=='ion_check':
                    for role in ION_FIXED:self.add_row(('ion_check',role),role,self.resolve(role,experiment,document),experiment,role,document,direct=False)
            else:
                exp=experiment or self.experiment.currentData()
                from .fpga_mapping import ROLES
                for role in ROLES.get(exp,tuple(DEFAULT_ROLES)):
                    pin=self.resolve(role,exp,document)
                    self.add_row((exp,role),role,pin,exp,role,document,direct=False)
            for table in (self.inputs,self.outputs):
                table.setMinimumHeight(min(420,max(100,table.rowCount()*38+38)))
            self.update_preview()
        finally:self._loading=False

    def add_row(self,key,title,selected,experiment,role,document,*,direct):
        input_pin=role in ('PMT','TRIGGER','DETECTOR','COUNTER','ION_PMT1','ION_PMT2') if direct else 'input' in capability(DEFAULT_ROLES[role])
        table=self.inputs if input_pin else self.outputs;row=table.rowCount();table.insertRow(row)
        combo=W.QComboBox();table.setItem(row,0,W.QTableWidgetItem(title));table.setCellWidget(row,1,combo)
        if direct and role in ('COUNTER','ION_PMT2'):combo.addItem('사용 안 함','')
        for pin in PINS:
            kind=capability(pin)
            if ('input' in kind)!=input_pin:continue
            allowed=(('counter' in kind) if input_pin else experiment=='fluorescence' or kind=='fast output') if direct else compatible(experiment,role,pin)
            if direct and experiment=='micromotion' and role!='COUNTER':allowed='stopwatch' in kind
            if direct and experiment=='ion_check' and not input_pin:allowed='output' in kind
            if direct and experiment=='phase_shifter' and not input_pin:
                allowed=kind=='slow output' if role.startswith('PHASE ') else kind=='fast output' if role=='microwave' else 'output' in kind
            combo.addItem(document['pins'][pin]+' ['+pin+']'+(' · 기능 미지원' if not allowed else ''),pin)
            combo.model().item(combo.count()-1).setEnabled(allowed)
            combo.setItemData(combo.count()-1,kind,QtCore.Qt.ToolTipRole)
        combo.setCurrentIndex(combo.findData(selected));self.rows[key]=combo
        table.setItem(row,2,W.QTableWidgetItem(capability(selected) if selected in PINS else '미지정'))
        def edit(*_):
            if self._loading:return
            name=self.target.currentData();pin=combo.currentData()
            if direct:self.overrides.setdefault(name,{})[key]=pin
            else:self.documents[name]['experiments'].setdefault(experiment,{})[role]=pin
            table.item(row,2).setText(capability(pin) if pin else '사용 안 함');self.update_preview();self.changed.emit()
        combo.currentIndexChanged.connect(edit)

    def update_preview(self):
        name=self.target.currentData()
        self.preview.setPlainText(json.dumps(self.documents.get(name,{}),ensure_ascii=False,indent=2))

    def value(self,parameters):
        name=self.target.currentData();document=deepcopy(self.documents.get(name))
        if document is None:raise ValueError('실행 FPGA를 연결하고 기본 매핑을 불러오세요.')
        parameters=deepcopy(parameters)
        for path,pin in self.overrides.get(name,{}).items():
            if self.experiment_name()=='ion_check':continue
            obj=parameters
            for key in path[:-1]:obj=obj[key]
            if self.experiment_name()=='scan':
                from labremote.devices.fpga.mapping import physical
                obj[path[-1]]=getattr(physical,pin+'_counter_result')
            elif self.experiment_name()=='phase_shifter':obj[path[-1]]=document['pins'][pin]
            else:obj[path[-1]]=pin
        if self.experiment_name()=='ion_check':
            chosen={path[-1]:self.overrides.get(name,{}).get(path,self.resolve(token,'ion_check',document))
                    for path,role,exp,token in self.direct_routes()}
            channels=parameters['settings'].setdefault('mapping',{})
            routes=document['experiments'].setdefault('ion_check',{})
            for key,pin in chosen.items():
                canonical=ION_CHANNELS[key][1]
                channels[key]=canonical if pin else None
                if pin:routes[canonical]=pin
        profile=Profile(deepcopy(document))
        for combo in self.rows.values():
            index=combo.currentIndex()
            if index<0 or not combo.model().item(index).isEnabled():
                raise ValueError('실험 기능에 맞는 입력·출력 핀을 선택하세요.')
        from labremote.devices.fpga.mapping import scope
        experiment=self.experiment_name()
        if experiment=='ion_check':
            from labremote.ion_check import config
            with scope(profile,'ion_check'):
                config.validate(parameters['settings'],require_thresholds=True)
                used=[profile.view('ion_check').output_mapping[role] for role in config.output_levels(parameters['settings'])]
                if len(set(used))!=len(used):raise ValueError('Ion Check의 레이저·EOM·MW 출력은 서로 다른 핀을 사용해야 합니다.')
        elif self.direct_routes() and experiment in ('fluorescence','rabi','initialization','ramsey','spam'):
            from labremote.characterization import config, rabi, pulse_experiment
            groups=parameters['settings'].values() if self.kind=='spam' and set(parameters['settings'])=={'EA','EC'} else [parameters['settings']]
            with scope(profile,experiment):
                for settings in groups:
                    if experiment=='fluorescence':config.validate_settings(settings)
                    elif experiment=='rabi':rabi.validate(settings)
                    else:pulse_experiment.validate(experiment,settings)
        elif experiment=='micromotion':
            from labremote.micromotion.config import validate
            with scope(profile,'micromotion'):validate(parameters['settings'])
        elif experiment=='phase_shifter':
            from labremote.phase_shifter import config,hold
            with scope(profile):
                c=parameters['settings']
                if self.kind=='phase_hold' or self.parameters.get('kind')=='PhaseHoldTab':hold.request(c['phase_angle_deg'],c['phase_outputs'],calibration=c.get('calibration'))
                elif self.parameters.get('kind')=='PhaseRabiTab':
                    from labremote.phase_shifter.rabi import validate
                    validate(c)
                else:config.validate(c)
        return parameters,profile.document()
