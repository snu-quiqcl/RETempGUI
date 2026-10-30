"""Windfreak transport identification; queue lifecycle is shared across families."""
from labremote.runtime.device_worker import DeviceWorker
from labremote.runtime.io import acquire


class WindfreakWorker(DeviceWorker):
    family = 'windfreak'

    def make_monitor(self):
        from labremote.devices.windfreak.monitor import WindfreakMonitor
        return WindfreakMonitor(self)

    def identify(self):
        acquire(self.ps.client_operation_version)
        return acquire(self.ps.device_info_json)
