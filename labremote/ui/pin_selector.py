from labremote.ui.responsive import bounded_combo
"""Physical pin selection with device aliases and legacy preset compatibility."""
from PyQt5 import QtCore, QtWidgets as W
from labremote.devices.fpga.mapping import PINS, DEFAULT_ROLES, capability


class PinSelector(W.QComboBox):
    def __init__(self, worker, experiment, *, input_pin=False, fast_only=False, slow_only=False):
        super().__init__();bounded_combo(self)
        self.worker, self.experiment = worker, experiment
        self.input_pin, self.fast_only, self.slow_only = input_pin, fast_only, slow_only
        self._token = None
        self._document = None
        self.currentIndexChanged.connect(self._selected)
        self.refresh()

    def _selected(self, index):
        pin = self.itemData(index)
        if pin in PINS:
            self._token = 'signal:' + self.worker.profile.document()['pins'][pin]
        elif pin is None:
            self._token = None

    def physical_pin(self, token):
        return self.worker.profile.resolve(token, self.experiment)

    def route(self):
        return self._token

    def setCurrentText(self, token):
        try:pin = self.physical_pin(token)
        except (ValueError, KeyError):pin = 'missing'
        index = self.findData(pin)
        if index < 0:
            self.addItem(str(token) + ' · 별칭 연결 확인 필요', 'missing')
            index = self.count()-1
            self.model().item(index).setEnabled(False)
        with QtCore.QSignalBlocker(self):self.setCurrentIndex(index)
        self._token = ('signal:' + self.worker.profile.document()['pins'][pin]) if pin and pin != 'missing' else (token if pin == 'missing' else None)

    def refresh(self):
        document = self.worker.profile.document()
        if document == self._document:return
        token = self._token
        with QtCore.QSignalBlocker(self):
            self.clear()
            self.addItem('미지정 — 공통 별칭 선택 필요', None)
            for pin in PINS:
                kind = capability(pin)
                if ('input' in kind) != self.input_pin:continue
                reason = ('카운터 미지원' if self.input_pin and 'counter' not in kind else
                          '이 시퀀스는 fast output 필요' if self.fast_only and kind!='fast output' else
                          'MW는 slow output 필요' if self.slow_only and kind!='slow output' else '')
                self.addItem(document['pins'][pin]+' ['+pin+']'+(' · '+reason if reason else ''), pin)
                item = self.model().item(self.count()-1)
                item.setEnabled(not reason)
                item.setToolTip(kind+(' · '+reason if reason else ''))
        self._document = document
        if token is not None:self.setCurrentText(token)
        else:self._selected(self.currentIndex())
