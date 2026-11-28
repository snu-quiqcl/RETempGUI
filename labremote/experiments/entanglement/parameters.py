"""Identical RE condition controls in experiment tabs and workflow editors."""
from PyQt5 import QtWidgets

def add_fields(form, config_module):
    basis=QtWidgets.QComboBox()
    basis.addItem('ZZ basis','zz');basis.addItem('MW detuned','mw_detuned')
    form.addRow('Measurement basis',basis)
    fields={}
    for key,label,lo,hi,decimals in config_module.FIELDS:
        box=QtWidgets.QDoubleSpinBox() if decimals else QtWidgets.QSpinBox()
        if decimals:box.setDecimals(decimals)
        box.setRange(lo,hi);box.setKeyboardTracking(False)
        if key.startswith('pi_'):box.setSingleStep(.02)
        elif key=='mirror_wait_ms':box.setSingleStep(.5)
        elif key.endswith('_us'):box.setSingleStep(.01)
        form.addRow(label,box);fields[key]=box
    return basis,fields

def readout_note(experiment):
    if experiment=='entanglement_no_mirror':
        return ('EA → EC 순차 측정 · 동일한 PMT 2개 사용 · 각 챔버 합산값으로 판정\n'
                'EA/EC detection time·threshold 개별 설정 · CCD 출력 변경 없음')
    return 'EA·EC 동시 측정 · EA 전용 PMT 1개 + EC 전용 PMT 1개 · flip mirror 전환 사용'
