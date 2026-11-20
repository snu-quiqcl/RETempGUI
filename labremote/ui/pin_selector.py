from labremote.ui.responsive import bounded_combo
"""Physical pin selection with device aliases and legacy preset compatibility."""
from PyQt5 import QtCore, QtWidgets as W
from labremote.devices.fpga.mapping import PINS, DEFAULT_ROLES, capability


class PinSelector(W.QComboBox):
    def __init__(self, worker, experiment, *, input_pin=False, fast_only=False):
        super().__init__();bounded_combo(self)
        self.worker, self.experiment = worker, experiment
        self.input_pin, self.fast_only = input_pin, fast_only
        self._token = None
        self._document = None
        self.currentIndexChanged.connect(self._selected)
        self.refresh()

    def _selected(self, index):
        pin = self.itemData(index)
        self._token = 'signal:' + self.worker.profile.document()['pins'][pin] if pin else None

    def physical_pin(self, token):
        return self.worker.profile.resolve(token, self.experiment)

    def route(self):
        return self._token

    def setCurrentText(self, token):
        pin = self.physical_pin(token)
        index = self.findData(pin)
        if index < 0:raise ValueError('Unknown input/output pin: '+str(token))
        with QtCore.QSignalBlocker(self):self.setCurrentIndex(index)
        self._token = 'signal:' + self.worker.profile.document()['pins'][pin] if pin else token

    def refresh(self):
        document = self.worker.profile.document()
        if document == self._document:return
        token = self._token
        with QtCore.QSignalBlocker(self):
            self.clear()
            if not self.input_pin:self.addItem('미지정 — 출력 핀 선택 필요', None)
            for pin in PINS:
                kind = capability(pin)
                if ('input' in kind) != self.input_pin:continue
                reason = ('카운터 미지원' if self.input_pin and 'counter' not in kind else
                          '이 시퀀스는 fast output 필요' if self.fast_only and kind!='fast output' else '')
                self.addItem(document['pins'][pin]+' ['+pin+']'+(' · '+reason if reason else ''), pin)
                item = self.model().item(self.count()-1)
                item.setEnabled(not reason)
                item.setToolTip(kind+(' · '+reason if reason else ''))
        self._document = document
        if token is not None:self.setCurrentText(token)
        else:self._selected(self.currentIndex())
