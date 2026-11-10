"""Nickname selection component for FPGA / etc.

The caller supplies the same loaded hardware definition used by the sequencer.
apply_to(parameters) returns the selected nicknames for build_program(..., hd).
This widget performs no hardware writes.
"""
from copy import deepcopy

from PyQt5 import QtCore, QtWidgets


class PhaseShifterEtcTab(QtWidgets.QWidget):
    selection_changed = QtCore.pyqtSignal()
    roles = (('aom', 'AOM'), ('eom_7g_1', 'EOM 7G1'),
             ('eom_7g_2', 'EOM 7G2'), ('eom_2g', 'EOM 2G'),
             ('microwave', 'Microwave'))

    def __init__(self, hd, parent=None):
        super().__init__(parent)
        self.hd = hd
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        signal_group = QtWidgets.QGroupBox('Experiment signals')
        signal_form = QtWidgets.QFormLayout(signal_group)
        phase_group = QtWidgets.QGroupBox('Phase bits · D0 = LSB, D11 = MSB')
        phase_form = QtWidgets.QGridLayout(phase_group)
        root.addWidget(signal_group)
        root.addWidget(phase_group)
        self.output_selectors = {}
        for role, label in self.roles:
            combo = QtWidgets.QComboBox()
            self.output_selectors[role] = combo
            signal_form.addRow(label, combo)
        self.detector_selector = QtWidgets.QComboBox()
        signal_form.addRow('PMT input', self.detector_selector)
        self.phase_selectors = []
        for i in range(12):
            combo = QtWidgets.QComboBox()
            self.phase_selectors.append(combo)
            combo.setMinimumContentsLength(10)
            combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
            column = 2 * (i // 6)
            phase_form.addWidget(QtWidgets.QLabel(f'D{i}'), i % 6, column)
            phase_form.addWidget(combo, i % 6, column + 1)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        root.addStretch()
        self.set_hardware_definition(hd)
        for combo in self._selectors():
            combo.currentIndexChanged.connect(self._changed)
        self._changed()

    def _selectors(self):
        return [*self.output_selectors.values(), self.detector_selector,
                *self.phase_selectors]

    def set_hardware_definition(self, hd):
        """Refresh from a loaded definition; retain only still-valid selections."""
        self.hd = hd
        outputs = list(hd.output_mapping)
        slow = [name for name, pin in hd.output_mapping.items()
                if pin.startswith(('jc_', 'jd_'))]
        fast = [name for name in outputs if name not in slow]
        detectors = list(dict.fromkeys(name for name in hd.input_mapping.values()
                         if all(hasattr(hd, name + suffix) for suffix in
                                ('_counter_enable', '_counter_reset', '_counter_result'))))

        def fill(combo, names):
            previous = combo.currentData()
            blocked = combo.blockSignals(True)
            try:
                combo.clear()
                combo.addItem('— nickname 선택 —', None)
                for name in names:
                    combo.addItem(name, name)
                index = combo.findData(previous) if previous is not None else 0
                combo.setCurrentIndex(max(0, index))
            finally:
                combo.blockSignals(blocked)

        for role, combo in self.output_selectors.items():
            fill(combo, fast if role == 'microwave' else outputs)
        for combo in self.phase_selectors:
            fill(combo, slow)
        fill(self.detector_selector, detectors)
        self._changed()

    def selection(self):
        selected = {role: combo.currentData()
                    for role, combo in self.output_selectors.items()}
        phase = [combo.currentData() for combo in self.phase_selectors]
        detector = self.detector_selector.currentData()
        if any(name is None for name in [*selected.values(), *phase, detector]):
            raise ValueError('각 신호와 D0~D11, PMT의 nickname을 모두 선택하세요.')
        pins = [self.hd.output_mapping[name] for name in [*selected.values(), *phase]]
        if len(pins) != len(set(pins)):
            raise ValueError('동일한 실제 출력을 여러 신호에 중복 지정할 수 없습니다.')
        return {'outputs': selected, 'phase_outputs': phase,
                'detector_nickname': detector}

    def apply_to(self, parameters):
        result = deepcopy(parameters)
        result.update(self.selection())
        return result

    def _changed(self, *_):
        try:
            self.selection()
        except ValueError as exc:
            self.status.setText(str(exc))
        else:
            self.status.setText('Nickname 선택 완료')
        self.selection_changed.emit()
