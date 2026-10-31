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
