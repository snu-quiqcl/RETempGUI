from labremote.runtime.device_worker import DeviceWorker
from labremote.runtime.io import acquire

class MDTWorker(DeviceWorker):
    family='mdt'
    def __init__(self):
        super().__init__()
        from labremote.runtime.pid_runner import PIDRunner
        self.pid_runner=PIDRunner(self)
    def make_monitor(self):
        from .monitor import Monitor
        return Monitor(self)
    def identify(self):
        acquire(self.ps.client_operation_version)
        return {'idn':'MDT693B'}
