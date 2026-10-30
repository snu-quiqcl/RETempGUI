from labremote.runtime.device_worker import DeviceWorker
from labremote.runtime.io import acquire
from labremote.runtime.monitor import ParameterMonitor
from labremote.runtime.errors import OperationCancelled


class OvenWorker(DeviceWorker):
    def __init__(self):
        super().__init__()
        self.io_fault = True  # Cleared only by a successful live connection check.

    def connect_device(self, host, port, name):
        self.io_fault = True
        return super().connect_device(host, port, name)

    def execute(self, handle):
        super().execute(handle)
        # InstrumentServer may wrap a server TimeoutError as a plain Exception.
        # Do not keep polling or permit another loading task after such errors.
        # Keep the proxy available for independent OFF/CLOSE cleanup attempts.
        if handle.error is not None and not isinstance(handle.error, OperationCancelled):
            self.io_fault = True
            self.cancel_backgrounds()


class OvenPSUWorker(OvenWorker):
    family = 'oven_psu'

    def make_monitor(self):
        return ParameterMonitor(self, ('output_enabled', 'ch1_measured_voltage', 'ch1_measured_current'))

    def identify(self):
        info = acquire(self.ps.IDN)
        if info.get('model') != 'E3631A': raise ConnectionError('Expected E3631A oven PSU')
        # E3631A.get_idn() is cached: it does not prove the serial port is alive.
        acquire(self.ps.output_enabled)
        acquire(self.ps.ch1_measured_voltage)
        acquire(self.ps.ch1_measured_current)
        self.io_fault = False
        return info


class OvenRelayWorker(OvenWorker):
    family = 'oven_relay'

    def make_monitor(self):
        return ParameterMonitor(self, ('selected_oven', 'shutter_1', 'shutter_2'))

    def identify(self):
        info = acquire(self.ps.IDN)
        if info.get('model') != 'RPiOvenRelay': raise ConnectionError('Expected RPiOvenRelay')
        acquire(self.ps.selected_oven)
        self.io_fault = False
        return info
