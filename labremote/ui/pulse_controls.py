"""Pin editors for the signals used by the pulse sequences and their cleanup."""
from PyQt5 import QtWidgets
from .pin_selector import PinSelector


def pin_controls(worker, kind, parent):
    group=QtWidgets.QGroupBox('이 실험의 FPGA 역할 매핑',parent)
    form=QtWidgets.QFormLayout(group)
    form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
    # All four operations also execute rabi.cleanup(), including MW OFF.
    labels=(('PMT','PMT · 검출 입력'),('AOM','AOM · 광 펄스'),
            ('MW','MW · 시작/종료 OFF' if kind=='initialization' else 'MW · 마이크로파 게이트'),
            ('EOM_7G_1','EOM 7G · 1'),('EOM_7G_2','EOM 7G · 2'),('EOM_2G','EOM 2G · 초기화'))
    roles={}
    for role,label in labels:
        box=PinSelector(worker,kind,input_pin=role=='PMT',fast_only=role!='PMT')
        box.setToolTip(label+' — 이 실험에서 사용할 실제 FPGA 핀')
        form.addRow(label,box);roles[role]=box
    note=QtWidgets.QLabel('이 실험의 검출·광 제어·MW 게이트에 사용하는 핀만 표시합니다.' if kind!='initialization' else
                         'MW 펄스는 사용하지 않습니다. 시작·종료 시 MW를 OFF로 만드는 핀은 유지합니다.')
    note.setWordWrap(True);form.addRow(note)
    return group,roles
