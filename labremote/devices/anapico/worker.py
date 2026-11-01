from labremote.runtime.device_worker import DeviceWorker
from labremote.runtime.io import acquire


class AnaPicoWorker(DeviceWorker):
    family = 'anapico'
    def make_monitor(self):
        from labremote.devices.anapico.monitor import AnaPicoMonitor
        return AnaPicoMonitor(self)

    def identify(self):
        identity = acquire(self.ps.identity)
        if 'APSYN420' not in identity.upper():
            raise ConnectionError('Unexpected device identity: ' + identity)
        return {'idn': identity, 'family': self.family}
