from labremote.runtime.device_worker import DeviceWorker
from labremote.runtime.io import acquire

class KeithleyWorker(DeviceWorker):
    family = 'keithley'

    def make_monitor(self):
        from labremote.devices.keithley.monitor import KeithleyMonitor
        return KeithleyMonitor(self)

    def identify(self):
        return acquire(self.ps.IDN)
