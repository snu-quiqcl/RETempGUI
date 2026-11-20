from labremote.runtime.monitor import ParameterMonitor

PATHS = ('frequency', 'amplitude', 'offset', 'output', 'waveform',
         'amplitude_unit', 'load_impedance')


class AFG2105Monitor(ParameterMonitor):
    def __init__(self, worker):
        super().__init__(worker, PATHS)
