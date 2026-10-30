from labremote.runtime.acquisition_worker import AcquisitionWorker
from labremote.runtime.io import acquire

class MSO7054Worker(AcquisitionWorker):
    family = 'mso7054'

    def make_monitor(self):
        from labremote.devices.mso7054.monitor import MSO7054Monitor
        return MSO7054Monitor(self)

    def identify(self):
        acquire(self.ps.client_operation_version)
        return acquire(self.ps.device_info_json)
