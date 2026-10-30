from labremote.runtime.acquisition_worker import AcquisitionWorker
from labremote.runtime.io import acquire

class DS1052EWorker(AcquisitionWorker):
    family = 'ds1052e'
    def make_monitor(self):
        from labremote.devices.ds1052e.monitor import DS1052EMonitor
        return DS1052EMonitor(self)

    def identify(self):
        acquire(self.ps.client_operation_version)
        return acquire(self.ps.device_info_json)
