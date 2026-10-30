from labremote.runtime.monitor import ParameterMonitor
PATHS = ('states',)

class Monitor(ParameterMonitor):
    def __init__(self, worker):super().__init__(worker, PATHS)
