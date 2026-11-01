"""One transport and FIFO operation queue per device instance."""
import queue
import threading
from types import SimpleNamespace
from PyQt5 import QtCore
from labremote.runtime.jobs import ExecutionHandle, CURRENT_JOB
from labremote.runtime.errors import OperationCancelled
from labremote.runtime.parameters import LIBRARY, bind_device, DeviceProxy
from labremote.runtime.network import configure_client_timeout

class DeviceWorker(QtCore.QThread):
    task_changed = QtCore.pyqtSignal(str, object)
    task_progress = QtCore.pyqtSignal(str, object)
    family = None
    connected = QtCore.pyqtSignal(object)
    disconnected = QtCore.pyqtSignal(str)
    snapshot = QtCore.pyqtSignal(object, str)
    completed = QtCore.pyqtSignal(str)
    failure = QtCore.pyqtSignal(str, str)
    ramp_active = QtCore.pyqtSignal(bool)
    busy_changed = QtCore.pyqtSignal(bool)
    reference_warning = QtCore.pyqtSignal(str)
    handle_changed = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self._queue = queue.Queue()
        self._lock = threading.RLock()
        self._pending = []
        self._active = None
        self._closing = False
        self._background_tasks = set()
        self.ui_heartbeat = None
        self._monitor_pending = set()
        self.monitor = self.make_monitor()
        self.operation_bridge = SimpleNamespace(worker=self)
        self.cli = self.ps = self.raw_device = None
        self.name = None
        self._execution_device = None
        self.connection_error = False
        self._timed_out = False
        self._snapshot = None
        from labremote.ui.library_updates import LibraryUpdates
        self.library_updates = LibraryUpdates(self)
        from .auto_monitor import AUTO_MONITOR
        AUTO_MONITOR.register(self)

    def make_monitor(self):
        raise NotImplementedError("Device family must supply its monitor")

    def enqueue(self, handle):
        with self._lock:
            if self._closing:
                handle.finish(OperationCancelled('Worker is shutting down'))
                return handle
            self._pending.append(handle)
            self._queue.put(handle)
        self.handle_changed.emit(handle)
        return handle

    def has_requests(self):
        with self._lock:
            return bool(self._pending or (self._active is not None and not self._active.done.is_set()))

    def command(self, action, *args):
        from labremote.api.devices import device_api
        return device_api(self, self.family).submit(action, *args)

    def cancel_backgrounds(self):
        from labremote.runtime.workflow_runner import _TASK_LOCK
        with _TASK_LOCK:tasks=tuple(self._background_tasks)
        for task in tasks:task.cancel()

    def cancel_pending(self):
        self.cancel_backgrounds()
        with self._lock:
            for handle in self._pending: handle.request_cancel()
            if self._active: self._active.request_cancel()

    def cancel_power_ramp(self):
        with self._lock:
            if self._active:
                if self._active.group: self._active.group.stop.set()
                else: self._active.request_cancel()

    def shutdown(self):
        with self._lock:
            self._closing = True
            self.cancel_pending()
        self._queue.put(None)

    def _disconnect(self):
        self.cancel_backgrounds()
        if self._execution_device: LIBRARY.invalidate(self._execution_device)
        if self.cli:
            try: self.cli.disconnect()
            except Exception: pass
        self.cli = self.ps = self.raw_device = None
        self._snapshot = None

    def disconnect_device(self):
        self._disconnect()
        self.disconnected.emit('Disconnected; hardware settings unchanged')

    def connect_device(self, host, port, name):
        self._disconnect()
        from labremote.runtime.transport import Client
        self._execution_device = (str(host), int(port), str(name))
        self.name = str(name)
        cli = Client(host=str(host), port=int(port), timeout=20000)
        configure_client_timeout(cli, 20)
        self.cli = cli
        try:
            if name not in cli.list_instruments(): raise ConnectionError(f'{name}: not registered on server')
            self.raw_device = self.prepare_device(cli.get_instrument(name))
            self.ps = bind_device(self, self.raw_device, self.family, name, host, port)
            info = self.identify()
        except Exception:
            self._disconnect()
            self.connection_error = True
            raise
        self.connection_error = self._timed_out = False
        self.monitor.register_parameters()
        self.connected.emit(info)

    def publish_snapshot(self, snapshot, label):
        from copy import deepcopy
        with self._lock: self._snapshot = deepcopy(snapshot)
        self.snapshot.emit(snapshot, label)

    def prepare_device(self, device):
        return device

    def refresh(self):
        from importlib import import_module
        self.monitor.register_parameters()
        read = import_module(f'labremote.operation.{self.family}.read_snapshot').read_snapshot
        self.publish_snapshot(read(self.ps), 'REFRESH')

    def scan_monitor(self, *, group=None):
        return self.monitor.scan(group=group)

    def execute(self, handle):
        from labremote.runtime.runner import OperationRunner
        OperationRunner.execute(self, handle)

    def run(self):
        try:
            while True:
                handle = self._queue.get()
                if handle is None: break
                with self._lock:
                    self._pending.remove(handle)
                    self._active = handle
                try: self.execute(handle)
                finally:
                    with self._lock:
                        self._active = None
        finally:
            from labremote.runtime.workflow_runner import _TASK_LOCK
            with _TASK_LOCK:tasks=tuple(self._background_tasks)
            self._disconnect()
            with self._lock:
                for handle in self._pending:
                    handle.finish(OperationCancelled('Worker stopped before execution'))
                self._pending.clear()
            for task in tasks:task.join()
