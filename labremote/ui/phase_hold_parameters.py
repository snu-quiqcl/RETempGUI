"""Queue editor for the existing persistent phase hold operation."""
from copy import deepcopy
from pathlib import Path
import json
from PyQt5 import QtWidgets as W
from labremote.phase_shifter.calibration import CalibrationSelector, resolve, estimate_note


class PhaseHoldParameters(W.QWidget):
    def __init__(self):
        super().__init__();self.target=None
        root=W.QVBoxLayout(self);self.target_form=W.QFormLayout();root.addLayout(self.target_form)
        self.angle=W.QDoubleSpinBox();self.angle.setRange(0,360);self.angle.setDecimals(6);self.angle.setSuffix(' °');self.angle.setValue(90)
        self.target_form.addRow('고정할 위상',self.angle)
        self.calibration=CalibrationSelector();root.addWidget(self.calibration)
        self.converted=W.QLabel();self.converted.setWordWrap(True);root.addWidget(self.converted)
        load=W.QPushButton('실험창에서 저장한 위상 고정 설정 불러오기…');root.addWidget(load);load.clicked.connect(self.load_settings)
        self.info=W.QLabel('보정 파일의 내용도 Queue 항목에 저장합니다. 원본 파일이 변경되어도 이 항목의 보정값은 유지됩니다.\n출력 D0~D11은 FPGA 핀 설정 탭에서 지정합니다. 적용한 위상은 다음 변경 명령 또는 FPGA 리셋까지 유지됩니다.')
        self.info.setWordWrap(True);root.addWidget(self.info);root.addStretch()
        self.angle.valueChanged.connect(self.preview);self.calibration.changed.connect(self.preview)
        self.loaded_outputs=None;self.preview()

    @staticmethod
    def defaults():return dict(fpga='',settings=dict(phase_angle_deg=90.,phase_outputs=[None]*12,calibration=None))

    def populate(self,parameters):
        settings=parameters['settings']
        self.angle.setValue(settings['phase_angle_deg']);self.calibration.set_table(deepcopy(settings.get('calibration')))
        self.loaded_outputs=deepcopy(settings.get('phase_outputs',[None]*12));self.preview()

    def parameters(self,base,validate=True):
        p=deepcopy(base);snapshot=self.calibration.active() if validate else (self.calibration.snapshot if self.calibration.mode.currentIndex() else None)
        p['fpga']=self.target.currentData() if self.target is not None else p.get('fpga','')
        p['settings']=dict(phase_angle_deg=self.angle.value(),phase_outputs=deepcopy(self.loaded_outputs or p.get('settings',{}).get('phase_outputs',[None]*12)),calibration=deepcopy(snapshot))
        if validate:resolve(p['settings']['phase_angle_deg'],snapshot)
        return p

    def preview(self,*_):
        try:
            value=resolve(self.angle.value(),self.calibration.active())
            self.converted.setText(f"변환 코드: {value['code']} / 4095 · 추정 위상: {value['applied_angle_deg']:.6f}°"+estimate_note(value))
        except Exception as exc:self.converted.setText(str(exc))

    def load_settings(self):
        path,_=W.QFileDialog.getOpenFileName(self,'위상 고정 설정 불러오기','','JSON (*.json)')
        if not path:return
        try:
            c=json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if not isinstance(c.get('phase_outputs'),list) or len(c['phase_outputs'])!=12:raise ValueError('D0~D11 설정 12개가 필요합니다.')
            resolve(c['phase_angle_deg'],c.get('calibration'))
            self.populate({'settings':c});self.info.setText('불러온 위상 고정 설정: '+path)
        except Exception as exc:self.info.setText('설정 확인: '+str(exc))
