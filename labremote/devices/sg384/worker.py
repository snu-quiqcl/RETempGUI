from labremote.runtime.device_worker import DeviceWorker
from labremote.runtime.io import acquire


class SG384Worker(DeviceWorker):
    family = 'sg384'
    def make_monitor(self):
        from labremote.devices.sg384.monitor import SG384Monitor
        return SG384Monitor(self)

    def identify(self):
        identity = acquire(self.ps.identity)
        if 'SG384' not in identity.upper():
            raise ConnectionError('Unexpected device identity: ' + identity)
        return {'idn': identity, 'family': self.family}
