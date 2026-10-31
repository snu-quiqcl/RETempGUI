from labremote.runtime.device_worker import DeviceWorker
from labremote.runtime.monitor import ParameterMonitor
from labremote.runtime.io import acquire


class FlipWorker(DeviceWorker):
    family='flip'
    def make_monitor(self):return ParameterMonitor(self,('position',))
    def identify(self):
        info=acquire(self.ps.IDN)
        if info.get('model') not in ('MFF101','MFF002'):raise ConnectionError('Expected MFF101/MFF002 flipper')
        acquire(self.ps.position)
        return info


from labremote.runtime.discovery import DiscoveryWorker


class FlipDiscoveryWorker(DiscoveryWorker):
    """Metadata discovery only; compatible with the window shutdown lifecycle."""
    name='flipper discovery'
    def __init__(self,parent=None):
        super().__init__(parent);self._background_tasks=set()
    def cancel_backgrounds(self):
        self.shutdown()
