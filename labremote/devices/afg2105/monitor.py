from labremote.runtime.monitor import ParameterMonitor

PATHS = ('amplitude_unit', 'load_impedance', 'waveform',
         'frequency', 'amplitude', 'offset', 'output')


class AFG2105Monitor(ParameterMonitor):
    def __init__(self, worker):
        super().__init__(worker, PATHS)
