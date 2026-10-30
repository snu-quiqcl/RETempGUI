from labremote.runtime.monitor import ParameterMonitor
PATHS = ('output_limit_v', 'software_minimum', 'software_maximum', 'master_scan_enabled', 'x.voltage', 'x.minimum', 'x.maximum', 'y.voltage', 'y.minimum', 'y.maximum', 'z.voltage', 'z.minimum', 'z.maximum')

class Monitor(ParameterMonitor):
    def __init__(self, worker):super().__init__(worker, PATHS)
