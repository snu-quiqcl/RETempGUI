from labremote.runtime.acquisition_worker import AcquisitionWorker
from labremote.runtime.io import acquire

class ThermotekWorker(AcquisitionWorker):
    family = 'thermotek'
    repeat_method = 'read_telemetry'

    def make_monitor(self):
        from labremote.devices.thermotek.monitor import ThermotekMonitor
        return ThermotekMonitor(self)

    def identify(self):
        acquire(self.ps.client_operation_version)
        return {'idn':'ThermoTek T257P'}
