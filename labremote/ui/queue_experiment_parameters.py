"""Edit built-in Queue experiment conditions without touching their pin routes."""
from copy import deepcopy
import math
from PyQt5 import QtWidgets as W


class ExperimentParameters(W.QWidget):
    def __init__(self,parameters):
        super().__init__();self.fields={};self.types={}
        root=W.QVBoxLayout(self)
        note=W.QLabel('현재 Queue 항목의 실험 조건입니다. 입력·출력은 FPGA · 핀 설정 탭에서 지정합니다.')
        note.setWordWrap(True);root.addWidget(note)
        scroll=W.QScrollArea();scroll.setWidgetResizable(True);root.addWidget(scroll)
        body=W.QWidget();scroll.setWidget(body);form=W.QFormLayout(body)
        excluded={'schema_version','roles','mapping','phase_outputs','outputs','detector_nickname','trg_pin','pmt_pin','counter_pin','pmt','hardware_definition_module'}
        for key,value in parameters.get('settings',{}).items():
            if key in excluded or type(value) not in (str,int,float,bool):continue
            widget=W.QCheckBox() if type(value) is bool else W.QLineEdit()
            self.fields[key]=widget;self.types[key]=type(value);form.addRow(key,widget)
        self.populate(parameters)

    def populate(self,parameters):
        for key,widget in self.fields.items():
            value=parameters['settings'][key]
            if self.types[key] is bool:widget.setChecked(value)
            else:widget.setText(str(value))

    def parameters(self,base,validate=True):
        result=deepcopy(base)
        for key,widget in self.fields.items():
            kind=self.types[key]
            try:value=widget.isChecked() if kind is bool else kind(widget.text())
            except (ValueError,TypeError):raise ValueError(key+': 올바른 값을 입력하세요.')
            if kind is float and not math.isfinite(value):raise ValueError(key+': 유한한 숫자를 입력하세요.')
            result['settings'][key]=value
        return result
