"""Queue uses the same used-signal table as standalone experiments."""
from copy import deepcopy
import json
from types import SimpleNamespace
from PyQt5 import QtCore,QtWidgets as W
from labremote.devices.fpga.mapping import editing_settings,Profile,scope,OUTPUTS
from labremote.devices.fpga import routing
from .experiment_mapping import MappingEditor

KINDS = {'SpamScanTab':'spam','SecularScanPage':'secular','TwoRFCompensationPage':'micromotion','MotorScanTab':'scan','FluorescenceTab':'fluorescence','RabiTab':'rabi','DecayExperimentTab':'decay',
         'HOMTab':'hom','EntanglementTab':'entanglement','EntanglementNoMirrorTab':'entanglement_no_mirror','IonCheckTab':'ion_check',
         'MicromotionPage':'micromotion','PhaseShifterTab':'phase_shifter','PhaseHoldTab':'phase_shifter','PhaseRabiTab':'phase_shifter','HalfPiRamseyTab':'phase_shifter'}
class QueueFPGASettings(W.QWidget):
    changed=QtCore.pyqtSignal()
    def __init__(self,job,target,bindings_provider,kind=None):
        super().__init__();self.job=deepcopy(job);self.target=target;self.provider=bindings_provider;self.kind=kind
        self.parameters=deepcopy(job['parameters']);self.documents={k:Profile(v).document() for k,v in job.get('fpga_profiles',{}).items()}
        self.editors=[];self._loading=False
        root=W.QVBoxLayout(self);self.target_row=W.QHBoxLayout();root.addLayout(self.target_row)
        self.target_row.addWidget(target);self.status=W.QLabel();self.target_row.addWidget(self.status)
        self.reset=W.QPushButton('현재 FPGA 설정 다시 읽기');self.target_row.addWidget(self.reset)
        self.reset.clicked.connect(self.load_defaults);target.currentIndexChanged.connect(self.select_device)
        scroll=W.QScrollArea();scroll.setWidgetResizable(True);root.addWidget(scroll)
        body=W.QWidget();scroll.setWidget(body);self.layout_rows=W.QVBoxLayout(body)
        self.note=W.QLabel('이 항목의 매핑은 Queue 계획에만 저장됩니다. 탭 설정과 물리 배선은 바뀌지 않습니다.')
        self.note.setWordWrap(True);root.addWidget(self.note)
        self.preview=W.QPlainTextEdit(self);self.preview.hide()
        self.select_device()

    def worker(self):
        if self.provider is None:return None
        return next((b.worker for f,b in self.provider().values() if f=='fpga' and b.worker.name==self.target.currentData()
                     and b.worker.ps is not None and not b.worker.connection_error and not b.worker._closing),None)

    def select_device(self,*_):
        self.capture()
        name=self.target.currentData();worker=self.worker()
        if name and name not in self.documents and worker is not None:self.documents[name]=worker.profile.document()
        self.status.setText('연결됨' if worker else '저장된 설정 편집' if name in self.documents else 'FPGA 선택 필요')
        self.reset.setEnabled(worker is not None);self.rebuild();self.changed.emit()

    def experiment_name(self):
        p=self.parameters
        if p.get('kind')=='PulseExperimentTab':return p.get('experiment_kind','ramsey')
        return KINDS.get(p.get('kind')) or {'ion':'ion_check','spam':'spam','entanglement':'entanglement','entanglement_no_mirror':'entanglement_no_mirror','phase_hold':'phase_shifter','setup':'setup'}.get(self.kind)

    def groups(self):
        p=self.parameters;c=p.get('settings',{});exp=self.experiment_name()
        if self.kind=='spam' and set(c)=={'EA','EC'}:return []  # Import one legacy set before editing pins.
        if p.get('kind')=='SpamScanTab':return [(('settings','spam'),c.get('spam',{}),'spam',None)]
        if exp and exp!='setup':return [(('settings',),c,exp,p.get('mode',p.get('experiment_mode')))]
        # Custom workflows must declare their experiment settings explicitly.
        return [(('mapping_experiments',i,'settings'),v['settings'],v['experiment'],v.get('mode'))
                for i,v in enumerate(p.get('mapping_experiments',[]))
                if isinstance(v,dict) and isinstance(v.get('settings'),dict)]

    def capture(self):
        for path,editor in self.editors:
            routing.put(self.parameters,path,editor.apply(routing.get(self.parameters,path,{})))

    @property
    def rows(self):
        # Optional rows and rebuilt editors have one authoritative owner.
        return {prefix+path:box for prefix,editor in self.editors for path,box in editor.choices.items()}

    def set_parameters(self,parameters,*,replace_mapping=False):
        self.capture();new=deepcopy(parameters)
        # The conditions form does not own pin fields.
        if not replace_mapping:
            for path,editor in self.editors:
                routing.put(new,path,editor.apply(routing.get(new,path,{})))
        self.parameters=new;self.rebuild()

    def load_defaults(self,*_):
        worker=self.worker()
        if worker is None:return
        self.capture();self.documents[worker.name]=worker.profile.document();self.rebuild();self.changed.emit()

    def direct_routes(self):
        return [(prefix+r.path,r.role,exp,routing.get(c,r.path)) for prefix,c,exp,mode in self.groups() for r in routing.routes(exp,c,mode)]

    @staticmethod
    def resolve(token,experiment,document):
        try:return Profile(document).resolve(token,None if experiment in ('phase_shifter','scan','micromotion','secular') else experiment)
        except ValueError:return 'missing:'+str(token)

    def rebuild(self,*_):
        if self._loading:return
        self._loading=True
        try:
            while self.layout_rows.count():
                item=self.layout_rows.takeAt(0)
                if item.widget():item.widget().hide();item.widget().deleteLater()
            self.editors=[]
            document=self.documents.get(self.target.currentData())
            if document is None:return
            worker=SimpleNamespace(profile=Profile(document))
            for prefix,c,exp,mode in self.groups():
                editor=MappingEditor(worker,exp,c,mode=mode);self.layout_rows.addWidget(editor)
                self.editors.append((prefix,editor))
                editor.changed.connect(self.changed)
            if not self.editors:
                self.layout_rows.addWidget(W.QLabel('이 Workflow가 선언한 실험 매핑이 없습니다. 전체 FPGA 역할을 대신 표시하지 않습니다.'))
            self.layout_rows.addStretch()
            self.preview.setPlainText(json.dumps(document,ensure_ascii=False,indent=2))
        finally:self._loading=False

    @editing_settings(False)
    def value(self,parameters):
        name=self.target.currentData();document=deepcopy(self.documents.get(name))
        if document is None:raise ValueError('실행 FPGA의 저장된 공통 핀 설정이 필요합니다.')
        parameters=deepcopy(parameters)
        for path,editor in self.editors:routing.put(parameters,path,editor.apply(routing.get(parameters,path,{})))
        profile=Profile(document)
        experiment=self.experiment_name()
        for prefix,c,exp,mode in self.groups():
            current=routing.get(parameters,prefix)
            with scope(profile,exp):routing.validate(current,exp,mode)
        if experiment=='ion_check':
            from labremote.experiments.ion_check import config
            with scope(profile,'ion_check'):
                config.validate(parameters['settings'],require_thresholds=True)
                used=[OUTPUTS[role][0] for role in config.output_levels(parameters['settings'])]
                if len(set(used))!=len(used):raise ValueError('Ion Check의 레이저·EOM·MW 출력은 서로 다른 핀을 사용해야 합니다.')
        elif self.direct_routes() and experiment in ('fluorescence','rabi','initialization','ramsey','spin_echo','spam'):
            from labremote.experiments.characterization.shared import config, pulse_model as pulse_experiment; from labremote.experiments.characterization.rabi import model as rabi
            groups=[parameters['settings']]
            if parameters.get('kind')=='SpamScanTab':groups=[parameters['settings']['spam']]
            with scope(profile,experiment):
                for settings in groups:
                    if experiment=='fluorescence':config.validate_settings(settings)
                    elif experiment=='rabi':rabi.validate(settings)
                    else:pulse_experiment.validate(experiment,settings)
                if parameters.get('kind')=='SpamScanTab':
                    from labremote.experiments.characterization.spam_scan.model import validate
                    validate(parameters['settings'])
        elif experiment=='secular':
            from labremote.experiments.micromotion.secular.config import validate
            with scope(profile):validate(parameters['settings'])
        elif experiment=='micromotion':
            from labremote.experiments.micromotion.config import validate
            with scope(profile):
                if parameters.get('kind')=='TwoRFCompensationPage':
                    from labremote.experiments.micromotion.two_rf import validate as validate_two_rf
                    validate_two_rf(parameters['settings'])
                else:validate(parameters['settings'], mode=parameters.get('mode', 'correlation'))
        elif experiment=='phase_shifter':
            from labremote.experiments.phase_shifter import config, hold
            with scope(profile):
                c=parameters['settings']
                if self.kind=='phase_hold' or self.parameters.get('kind')=='PhaseHoldTab':hold.request(c['phase_angle_deg'],c['phase_outputs'],calibration=c.get('calibration'))
                elif self.parameters.get('kind')=='PhaseRabiTab':
                    from labremote.experiments.phase_shifter.rabi import validate
                    validate(c)
                else:config.validate(c)
        elif experiment in ('hom','entanglement','entanglement_no_mirror','decay'):
            from importlib import import_module
            model=import_module('labremote.experiments.'+experiment+'.config')
            with scope(profile,experiment):model.validate(parameters['settings'])
        return parameters,profile.document()
