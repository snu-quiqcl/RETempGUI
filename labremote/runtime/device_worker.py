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
        self._execution_owner = None
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
            owner=getattr(handle.group,'owner',None)
            automatic=getattr(handle,'automatic_monitor',False)
            repeat_handle=getattr(getattr(self,'waveform_runner',None),'handle',None)
            terminating=handle.action=='DISCONNECT' or (handle.action=='ABORT' and repeat_handle is not None and repeat_handle.cancelled())
            try:
                current=self.execution_owner()
                if current is not None and current is not owner and not terminating:
                    if automatic:
                        self._monitor_pending.discard(handle.monitor_key)
                        handle.finish();return handle
                    raise self._ownership_error(handle.action)
                if owner is not None and not terminating:self.reserve_execution(owner,shared=self in getattr(handle.group,'shared_workers',()))
            except Exception as error:
                self._monitor_pending.discard(handle.monitor_key)
                handle.finish(error);self.handle_changed.emit(handle);return handle
            self._pending.append(handle)
            self._queue.put(handle)
        self.handle_changed.emit(handle)
        return handle

    def _ownership_error(self,action):
        from .errors import ResourceBusy
        return ResourceBusy(f'{self.name or self.family}: {action} blocked; device reserved by {self.execution_owner()}')

    def reserve_execution(self,owner,shared=False):
        """Fail fast for another owner; automatic reads drain on this FIFO."""
        with self._lock:
            current=self.execution_owner()
            if current is owner:return False
            if current is not None:raise self._ownership_error('execution')
            from .execution_scope import shared_owners
            shared_users=shared_owners(self)
            if shared and owner in shared_users:return False
            if not shared and shared_users-{owner}:
                from .errors import ResourceBusy
                raise ResourceBusy(f'{self.name or self.family}: device busy with shared executions')
            repeat=getattr(self,'waveform_runner',None)
            if repeat is not None and repeat.running() and getattr(getattr(repeat,'handle',None),'group',None) is not None and repeat.handle.group.owner is not owner:
                from .errors import ResourceBusy
                raise ResourceBusy(f'{self.name or self.family}: device busy with {repeat.label} [{repeat.handle.status}]')
            for h in [*self._pending,self._active]:
                if h is not None and not h.done.is_set() and not getattr(h,'automatic_monitor',False) and getattr(h.group,'owner',None) is not owner and not (shared and self in getattr(h.group,'shared_workers',())):
                    from .errors import ResourceBusy
                    raise ResourceBusy(f'{self.name or self.family}: device busy with {h.action} [{h.status}], request={h.request_id}')
            from .execution_scope import claim
            claim(self,owner,shared=shared)
            self._execution_owner=owner;owner.remember(self);return True

    def release_execution(self,owner):
        with self._lock:
            from .execution_scope import release
            release(self,owner)
            if self._execution_owner is owner:self._execution_owner=None

    def execution_owner(self):
        from .execution_scope import owner_for
        return owner_for(self)

    def check_execution(self,handle):
        """Also guard commands queued through another alias of this device."""
        with self._lock:
            owner=self.execution_owner()
            repeat_handle=getattr(getattr(self,'waveform_runner',None),'handle',None)
            terminating=handle.action=='DISCONNECT' or (handle.action=='ABORT' and repeat_handle is not None and repeat_handle.cancelled())
            if owner is not None and owner is not getattr(handle.group,'owner',None) and not terminating:
                raise self._ownership_error(handle.action)

    def execution_reserved(self):
        from .execution_scope import shared_owners
        return self.execution_owner() is not None or bool(shared_owners(self))

    def has_foreground_requests(self):
        with self._lock:
            return any(h is not None and not h.done.is_set() and not getattr(h,'automatic_monitor',False) for h in [*self._pending,self._active])

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
        # Task admission uses task-lock -> worker-lock; never invert that order.
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
