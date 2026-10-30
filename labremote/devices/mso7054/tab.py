from labremote.devices.ds1052e.tab import DS1052ETab
from labremote.devices.mso7054.worker import MSO7054Worker
from PyQt5 import QtWidgets
from labremote.runtime.parameters import LIBRARY


class MSO7054Tab(DS1052ETab):
    channels=('CH1','CH2','CH3','CH4')
    worker_type=MSO7054Worker
    scope_title='MSO7054 four-channel screen acquisition'
    sample_note='MSO7054 screen samples with preamble calibration, not deep memory'
    display_on=True
    trigger_mode_path='trigger_type'
    trigger_sweep_path='sweep'
    first_measurement='vavg'
    first_measurement_title='Vavg'
    first_measurement_unit='V'
    slopes=('POS','NEG','RFAL')
    sweeps=('AUTO','NORM')
    shared_waveform_path='waveform_data'

    def _build(self):
        super()._build()
        box=QtWidgets.QGroupBox('Additional measurements');grid=QtWidgets.QGridLayout(box)
        self.extra_measurements={}
        for n,ch in enumerate(self.channels):
            grid.addWidget(QtWidgets.QLabel(ch),n,0)
            for column,field in enumerate(('vrms','vmax','vmin'),start=1):
                label=QtWidgets.QLabel(field.upper()+': Unknown')
                self.extra_measurements[ch.lower()+'_'+field]=label;grid.addWidget(label,n,column)
        self.layout().addWidget(box)

    def _settings(self,data,source):
        super()._settings(data,source)
        for path,label in self.extra_measurements.items():
            state=LIBRARY.read((self.worker._execution_device,path))
            value=state.observed if self.connected and state.quality=='valid' else None
            label.setText(path.split('_')[1].upper()+': '+('Unavailable' if value is None else f'{value:.8g} V'))
