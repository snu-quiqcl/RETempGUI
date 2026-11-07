"""EA/EC Queue forms share the standalone SPAM field definitions and validation."""
from copy import deepcopy
from PyQt5 import QtWidgets
from labremote.characterization import pulse_experiment as model,rabi,config


class SpamParameters(QtWidgets.QWidget):
    def __init__(self):
        super().__init__();self.fields={};self.roles={}
        layout=QtWidgets.QVBoxLayout(self);form=QtWidgets.QFormLayout();layout.addLayout(form)
        self.fpga=QtWidgets.QLineEdit('fpga_local');form.addRow('FPGA 장비',self.fpga)
        note=QtWidgets.QLabel('Workflow 1회: EA SPAM → EC SPAM. 각 챔버 설정을 이 Queue 항목에 저장합니다.\nMW 주파수·출력은 외부에서 설정합니다. 시간 입력 단위는 µs입니다.');note.setWordWrap(True);layout.addWidget(note)
        self.chambers=QtWidgets.QTabWidget();layout.addWidget(self.chambers,1)
        for chamber in ('EA','EC'):
            page=QtWidgets.QWidget();body=QtWidgets.QVBoxLayout(page);self.chambers.addTab(page,chamber+' SPAM')
            bar=QtWidgets.QHBoxLayout();body.addLayout(bar)
            saved=QtWidgets.QPushButton('저장된 '+chamber+' SPAM 설정 불러오기');file=QtWidgets.QPushButton('설정 파일 불러오기…');bar.addWidget(saved);bar.addWidget(file);bar.addStretch()
            saved.clicked.connect(lambda _,ch=chamber:self.load_chamber(ch))
            file.clicked.connect(lambda _,ch=chamber:self.choose_file(ch))
            scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);body.addWidget(scroll)
            contents=QtWidgets.QWidget();scroll.setWidget(contents);grid=QtWidgets.QHBoxLayout(contents)
            measurement=QtWidgets.QGroupBox('측정 조건');inputs=QtWidgets.QFormLayout(measurement);grid.addWidget(measurement)
            mapping=QtWidgets.QGroupBox('FPGA 역할 매핑');mapped=QtWidgets.QFormLayout(mapping);grid.addWidget(mapping)
            self.fields[chamber]={};self.roles[chamber]={}
            for key,title,lo,hi,dec,step in model.fields('spam'):
                field=QtWidgets.QDoubleSpinBox() if dec else QtWidgets.QSpinBox()
                if dec:field.setDecimals(dec)
                field.setRange(lo,hi);field.setSingleStep(step);field.setKeyboardTracking(False)
                self.fields[chamber][key]=field;inputs.addRow(title,field)
            for role,names in rabi.ROLE_CHOICES.items():
                box=QtWidgets.QComboBox();box.addItems(names);self.roles[chamber][role]=box;mapped.addRow(role,box)
            self.populate_chamber(chamber,model.defaults('spam',chamber))
        self.info=QtWidgets.QLabel('불러오기는 Queue 편집값만 바꾸며, 기존 실험 설정 파일은 덮어쓰지 않습니다.');self.info.setWordWrap(True);layout.addWidget(self.info)

    @staticmethod
    def defaults():return dict(fpga='fpga_local',settings={ch:model.load('spam',ch) for ch in ('EA','EC')})

    @staticmethod
    def validate_parameters(parameters):
        if not isinstance(parameters,dict):raise ValueError('Parameters must be an object')
        name=parameters.get('fpga','fpga_local')
        if not isinstance(name,str) or not name.strip():raise ValueError('FPGA 장비 이름을 입력하세요.')
        settings=parameters.get('settings')
        if not isinstance(settings,dict) or set(settings)!={'EA','EC'}:raise ValueError('EA와 EC SPAM 설정이 모두 필요합니다.')
        for ch in ('EA','EC'):
            c=model.validate('spam',settings[ch])
            if c['chamber']!=ch:raise ValueError(ch+' SPAM chamber/settings mismatch')
        return deepcopy(parameters)

    def populate_chamber(self,chamber,c):
        c=model.validate('spam',c)
        if c['chamber']!=chamber:raise ValueError(chamber+'용 설정 파일을 선택하세요.')
        for key,field in self.fields[chamber].items():field.setValue(c[key]/100 if key in model.times('spam') else c[key])
        for role,box in self.roles[chamber].items():box.setCurrentText(c['roles'][role])

    def populate(self,parameters):
        self.validate_parameters(parameters);self.fpga.setText(parameters.get('fpga','fpga_local'))
        for ch in ('EA','EC'):self.populate_chamber(ch,parameters['settings'][ch])

    def parameters(self,base,validate=True):
        p=deepcopy(base);p['fpga']=self.fpga.text().strip();p['settings']={}
        for ch in ('EA','EC'):
            c=dict(schema_version=1,experiment='spam',chamber=ch,roles={k:b.currentText() for k,b in self.roles[ch].items()})
            for key,field in self.fields[ch].items():c[key]=round(field.value()*100) if key in model.times('spam') else field.value()
            p['settings'][ch]=c
        return self.validate_parameters(p) if validate else p

    def choose_file(self,chamber):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,chamber+' SPAM 설정 불러오기',str(config.ROOT),'JSON (*.json)')
        if path:self.load_chamber(chamber,path)

    def load_chamber(self,chamber,path=None):
        try:
            self.populate_chamber(chamber,model.load('spam',chamber,path))
            self.info.setText(chamber+' 설정을 불러왔습니다: '+(str(path) if path else '저장된 실험 설정'))
        except Exception as exc:self.info.setText('설정 확인: '+str(exc))
