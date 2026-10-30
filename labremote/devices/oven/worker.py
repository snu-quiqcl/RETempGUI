from labremote.runtime.device_worker import DeviceWorker
from labremote.runtime.io import acquire
from labremote.runtime.monitor import ParameterMonitor


class OvenPSUWorker(DeviceWorker):
    family = 'oven_psu'

    def make_monitor(self):
        return ParameterMonitor(self, ('output_enabled', 'ch1_measured_voltage', 'ch1_measured_current'))

    def identify(self):
        info = acquire(self.ps.IDN)
        if info.get('model') != 'E3631A': raise ConnectionError('Expected E3631A oven PSU')
        return info


class OvenRelayWorker(DeviceWorker):
    family = 'oven_relay'

    def make_monitor(self):
        return ParameterMonitor(self, ('selected_oven', 'shutter_1', 'shutter_2'))

    def identify(self):
        info = acquire(self.ps.IDN)
        if info.get('model') != 'RPiOvenRelay': raise ConnectionError('Expected RPiOvenRelay')
        return info
