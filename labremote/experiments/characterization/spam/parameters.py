"""One SPAM parameter form per Workflow/Queue item."""
from copy import deepcopy
from PyQt5 import QtCore, QtWidgets as W
from labremote.devices.fpga.mapping import editing_settings, scope
from labremote.experiments.characterization.shared import pulse_model as model, config
from labremote.experiments.characterization.spam import config as workflow_config


class SpamParameters(W.QWidget):
    settings_loaded=QtCore.pyqtSignal()

    @editing_settings()
    def __init__(self):
        super().__init__()
        self.fields={};self._pending_legacy=None
        layout=W.QVBoxLayout(self);form=W.QFormLayout();layout.addLayout(form)
        self.fpga=W.QLineEdit();form.addRow('FPGA 장비',self.fpga)
        self.fpga.setPlaceholderText('FPGA · 핀 설정 탭에서 장비를 선택하세요.')
        note=W.QLabel('이 항목의 핀 매핑과 측정 변수 한 세트로 SPAM을 실행합니다. 이름은 위에서 자유롭게 지정하세요.\n'
                      '측정 전후 지정한 냉각 출력으로 복귀합니다. Flip mirror·CCD는 제어하지 않습니다.\n'
                      'MW 주파수·출력은 외부에서 설정합니다. 시간 입력 단위는 µs입니다.')
        note.setWordWrap(True);layout.addWidget(note)
        self.file_button=W.QPushButton('설정 파일 불러오기…');layout.addWidget(self.file_button)
        self.file_button.clicked.connect(self.choose_file)
        self.legacy_box=W.QGroupBox('이전 Queue에서 설정 한 세트 가져오기')
        legacy=W.QHBoxLayout(self.legacy_box)
        for chamber in ('EA','EC'):
            button=W.QPushButton('기존 '+chamber+' 설정 가져오기')
            button.clicked.connect(lambda _,ch=chamber:self.import_legacy(ch));legacy.addWidget(button)
        layout.addWidget(self.legacy_box)
        self.measurement=W.QGroupBox('측정 조건');inputs=W.QFormLayout(self.measurement)
        for key,title,lo,hi,dec,step in model.fields('spam'):
            field=W.QDoubleSpinBox() if dec else W.QSpinBox()
            if dec:field.setDecimals(dec)
            field.setRange(lo,hi);field.setSingleStep(step);field.setKeyboardTracking(False)
            self.fields[key]=field;inputs.addRow(title,field)
        scroll=W.QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(self.measurement)
        layout.addWidget(scroll,1)
        self.info=W.QLabel('불러오기는 이 Queue 항목만 변경하며 기존 설정 파일은 덮어쓰지 않습니다.')
        self.info.setWordWrap(True);layout.addWidget(self.info)
        self.populate(self.defaults())

    @staticmethod
    @editing_settings()
    def defaults():
        return dict(fpga='fpga_local',settings=model.defaults('spam',None))

    @staticmethod
    @editing_settings()
    def validate_parameters(parameters):
        return workflow_config.parameters(parameters)

    @editing_settings()
    def populate(self,parameters):
        if workflow_config.paired(parameters) and parameters.get('chamber') not in ('EA','EC'):
            self.fpga.setText(parameters.get('fpga','fpga_local'))
            self._pending_legacy=deepcopy(parameters)
            self.legacy_box.show();self.measurement.hide()
            self.info.setText('이전 항목에 두 설정이 있습니다. 사용할 설정 한 세트를 가져오세요. 적용 전 원본 Queue는 바뀌지 않습니다.')
            return
        p=workflow_config.parameters(parameters,require_fpga=False);c=p['settings']
        self.fpga.setText(p.get('fpga','fpga_local'))
        self._pending_legacy=None;self._parameters=p;self._settings=deepcopy(c)
        for key,field in self.fields.items():
            field.setValue(c[key]/100 if key in model.times('spam') else c[key])
        self.legacy_box.hide();self.measurement.show()

    @editing_settings()
    def parameters(self,base,validate=True):
        if self._pending_legacy is not None:
            if validate:raise ValueError('이전 Queue에서 사용할 설정 한 세트를 먼저 가져오세요.')
            # Keep both legacy sets intact while navigating to device/pin settings.
            return dict(deepcopy(self._pending_legacy),fpga=self.fpga.text().strip())
        p=deepcopy(base);p.pop('chamber',None)
        p['fpga']=self.fpga.text().strip();c=deepcopy(self._settings)
        for key,field in self.fields.items():
            c[key]=round(field.value()*100) if key in model.times('spam') else field.value()
        p['settings']=c
        if isinstance(p.get('frequency_hz'),dict):p['frequency_hz']=self._parameters.get('frequency_hz')
        return self.validate_parameters(p) if validate else p

    @editing_settings()
    def import_legacy(self,chamber):
        try:
            draft=dict(self._pending_legacy,fpga=self.fpga.text().strip())
            p=workflow_config.parameters(draft,legacy_chamber=chamber,require_fpga=False)
            self.populate(p);self.settings_loaded.emit()
            self.info.setText('기존 '+chamber+'의 변수·핀 설정 한 세트를 가져왔습니다. 이름은 직접 지정하세요.')
        except Exception as exc:self.info.setText('설정 확인: '+str(exc))

    def choose_file(self):
        path,_=W.QFileDialog.getOpenFileName(self,'SPAM 설정 불러오기',str(config.ROOT),'JSON (*.json)')
        if path:self.load_file(path)

    @editing_settings()
    def load_file(self,path):
        try:
            with scope(self.profile_provider(),'spam'):
                c=config.read(path)
                base=self._pending_legacy if self._pending_legacy is not None else self._parameters
                p=workflow_config.parameters(dict(base,fpga=self.fpga.text().strip(),settings=c))
            self.populate(p);self.settings_loaded.emit()
            self.info.setText('설정을 불러왔습니다: '+str(path))
        except Exception as exc:self.info.setText('설정 확인: '+str(exc))
