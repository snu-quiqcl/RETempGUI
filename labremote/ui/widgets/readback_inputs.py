"""Explicit, read-only requests to replace local input drafts with device values."""
from PyQt5 import QtWidgets


def add_readback_button(owner, layout, flag, ready, request):
    button = QtWidgets.QPushButton('현재값 가져오기')
    button.setToolTip('장비 값을 다시 읽어 입력란에 넣습니다. 장비 설정은 변경하지 않습니다.')
    def load():
        if not ready():
            return
        setattr(owner, flag, True)
        try:
            request()
        except Exception:
            setattr(owner, flag, False)
            raise
    button.clicked.connect(load)
    layout.addWidget(button)
    return button
