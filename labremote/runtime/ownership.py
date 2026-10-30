"""Operation-scoped device ownership only; no threads, execution or cancellation."""
from contextvars import ContextVar
import threading

CURRENT_OWNER = ContextVar('device_owner', default=None)


def device_id(host, port, name):
    host = str(host).strip().lower().rstrip('.')
    if host in ('localhost', '::1', '[::1]'): host = '127.0.0.1'
    return (host, int(port), str(name).strip())


class DeviceLease:
    def __init__(self, manager, devices):
        self.manager, self.devices = manager, devices

    def release(self):
        with self.manager._lock:
            for device in self.devices:
                if self.manager._owners.get(device) is self:
                    del self.manager._owners[device]


class OwnershipManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._owners = {}

    def owner(self, device):
        with self._lock: return self._owners.get(device)

    def acquire(self, devices):
        from labremote.runtime.errors import ResourceBusy
        devices = frozenset(devices)
        with self._lock:
            if any(device in self._owners for device in devices):
                raise ResourceBusy('Device already has an operation owner')
            lease = DeviceLease(self, devices)
            for device in devices: self._owners[device] = lease
            return lease


DEFAULT_MANAGER = OwnershipManager()
