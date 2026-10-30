"""Motor operations use the same InstrumentServer transport as RF devices."""
from PyQt5 import QtCore
from labremote.runtime.parameters import LIBRARY
from labremote.runtime.device_worker import DeviceWorker
from labremote.runtime.io import acquire
from labremote.runtime.network import configure_client_timeout
from labremote.config.device_config import load_device_config


class MotorWorker(DeviceWorker):
    family = 'motors'
    identity_warning = QtCore.pyqtSignal(str)

    def execute(self, handle):
        super().execute(handle)
        state = LIBRARY.read((self._execution_device, 'status'))
        value = state.observed if state.quality == 'valid' else None
        if not isinstance(value, dict):return
        warning = value.get('identity_warning')
        warning_id = value.get('identity_warning_id')
        if warning and warning_id and warning_id != getattr(self, '_last_identity_warning', None):
            self._last_identity_warning = warning_id
            self.identity_warning.emit(warning)

    def make_monitor(self):
        from .monitor import Monitor
        return Monitor(self)

    def identify(self):
        # Home/full travel can take longer than other instruments' requests.
        timeout = load_device_config(self.family, self.name)['connection']['timeout_s']
        configure_client_timeout(self.cli, timeout)
        return acquire(self.ps.status)
