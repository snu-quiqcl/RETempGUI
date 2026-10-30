"""Local arrow-key increments; changing a step never sends hardware commands."""
from PyQt5 import QtWidgets

FREQUENCY_SCALES = {'GHz':1e9, 'MHz':1e6, 'kHz':1e3, 'Hz':1}
FREQUENCY_DECIMALS = {'GHz':9, 'MHz':6, 'kHz':3, 'Hz':0}


class StepControl(QtWidgets.QWidget):
    def __init__(self, target, unit):
        super().__init__()
        self.target = target
        self.unit = unit
        self.saved = {}
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QtWidgets.QLabel('Step'))
        self.edit = QtWidgets.QDoubleSpinBox()
        self.edit.setKeyboardTracking(False)
        self.edit.setToolTip('Increment for the value arrows / Up and Down keys. Apply/Set sends the value.')
        layout.addWidget(self.edit)
        self.unit_label = QtWidgets.QLabel(unit)
        layout.addWidget(self.unit_label)
        self.target_unit = unit
        self.units = None
        self.configure(unit, target.singleStep())
        self.edit.valueChanged.connect(self._apply)

    def _apply(self, *_):
        factor = (FREQUENCY_SCALES[self.unit]/FREQUENCY_SCALES[self.target_unit]
                  if self.units is not None and self.unit in FREQUENCY_SCALES else 1)
        self.target.setSingleStep(self.edit.value()*factor)

    def enable_frequency_units(self, choices):
        self.units=QtWidgets.QComboBox();self.units.addItems(choices)
        self.units.setCurrentText(self.unit);self.units.setFixedWidth(60)
        self.unit_label.hide();self.layout().addWidget(self.units)
        self.units.currentTextChanged.connect(self._frequency_unit)

    def _frequency_unit(self, unit):
        value=self.edit.value()*FREQUENCY_SCALES[self.unit]/FREQUENCY_SCALES[unit]
        self.unit=unit
        self.edit.setDecimals(FREQUENCY_DECIMALS[unit])
        self.edit.setRange(1/FREQUENCY_SCALES[unit],1e12)
        self.edit.setValue(value);self._apply()

    def set_target_unit(self, unit):
        self.target_unit=unit;self._apply()

    def configure(self, unit, value):
        self.unit = unit
        self.edit.setDecimals(self.target.decimals())
        self.edit.setRange(10 ** -self.target.decimals(), 1e12)
        self.edit.setSuffix('')
        self.unit_label.setText(unit)
        self.edit.setValue(value)
        self.target.setSingleStep(self.edit.value())

    def change_unit(self, unit):
        # dBm is logarithmic: preserve independent increments for dBm and Vpp.
        self.saved[self.unit] = self.edit.value()
        self.configure(unit, self.saved.get(unit, self.target.singleStep()))
