"""DDS v2 adapter: channel I/O uses parameters; status is exposed as read-only get.
Serial connect is explicit lifecycle work. Detach never calls device.disconnect().
"""
from labremote.runtime.device_worker import DeviceWorker
from labremote.runtime.io import acquire


class StatusParameter:
    def __init__(self, device): self.device = device
    def get(self): return self.device.get_status()


class DDSProxy:
    def __init__(self, device):
        self.device = device
        self.status_json = StatusParameter(device)
    def __getattr__(self, name): return getattr(self.device, name)


class DDS4Worker(DeviceWorker):
    family = 'dds4'
    def make_monitor(self):
        from labremote.devices.dds4.monitor import DDS4Monitor
        return DDS4Monitor(self)

    def prepare_device(self, device):
        return DDSProxy(device)

    def identify(self):
        state = acquire(self.ps.status_json)
        if state.get('faulted'):
            raise ConnectionError('DDS faulted; recover on the server before connecting')
        if not state.get('connected'):
            self.raw_device.connect()
            state = acquire(self.ps.status_json)
        if not state.get('connected') or state.get('faulted'):
            raise ConnectionError('DDS serial connection is unavailable')
        return dict(idn='AD9912 + VVA (4 channels)', **state)
