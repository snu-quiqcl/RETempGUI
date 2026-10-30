"""Thread-safe handles and operation execution; no UI or device transport."""
from dataclasses import dataclass, field
from contextvars import ContextVar
from contextlib import contextmanager
import threading
import time
from uuid import uuid4
from labremote.runtime.errors import OperationCancelled

class CancellationToken(threading.Event):
    """Serialize workflow cancellation with handle completion."""
    def __init__(self):
        super().__init__()
        self.lock = threading.RLock()

    def set(self):
        with self.lock: super().set()

CURRENT_JOB = ContextVar('current_job', default=None)
ATOMIC_ASSIGN = ContextVar('atomic_assign', default=False)

@dataclass
class ExecutionHandle:
    action: str
    callback: object
    group: object = None
    monitor_key: object = None
    request_id: str = field(default_factory=lambda: uuid4().hex)
    status: str = 'queued'
    error: object = None
    result: object = field(default=None, init=False)
    completed_at_ns: int = field(default=0, init=False)
    location: str = ''
    arguments: dict = field(default_factory=dict)
    write_guard: object = field(default=None,repr=False)
    done: object = field(default_factory=threading.Event)
    cancel_event: object = field(default_factory=threading.Event)
    _callbacks: list = field(default_factory=list)
    _lock: object = field(default_factory=threading.RLock)

    def cancelled(self):
        return self.cancel_event.is_set() or (self.group is not None and self.group.stop.is_set())

    def check_cancelled(self):
        if self.cancelled() and not ATOMIC_ASSIGN.get():
            raise OperationCancelled(f'{self.action}: cancelled at {self.location or self.status}; acquire affected values to confirm')

    def wait(self, timeout=None):
        # UI callers subscribe instead. Never return early on cancellation: an
        # in-flight assign must finish its readback before its owner can finish.
        if not self.done.wait(timeout):
            raise TimeoutError('Handle wait expired; operation is still pending')
        if self.error is not None:
            raise self.error
        return self.result

    def subscribe(self, callback):
        with self._lock:
            self._callbacks.append(callback)
        self._notify_one(callback)
        return lambda: self._unsubscribe(callback)

    def _unsubscribe(self, callback):
        with self._lock:
            if callback in self._callbacks: self._callbacks.remove(callback)

    def _notify_one(self, callback):
        try: callback(self)
        except Exception:
            import logging
            logging.exception('Execution observer failed')

    def notify(self):
        with self._lock: callbacks = tuple(self._callbacks)
        for callback in callbacks: self._notify_one(callback)

    def request_cancel(self):
        with self._lock:
            if self.done.is_set(): return False
            self.cancel_event.set()
            return True

    def finish(self, error=None, before_publish=None, *, result=None):
        from contextlib import nullcontext
        group_lock = getattr(getattr(self.group, 'stop', None), 'lock', None)
        with group_lock if group_lock is not None else nullcontext():
            with self._lock:
                if self.done.is_set(): return self.error
                if error is None and self.cancelled():
                    error = OperationCancelled(f'{self.action}: cancelled at {self.location or self.status}; acquire affected values to confirm')
                if before_publish is not None: before_publish(error)
                self.error = error
                self.result = result if error is None else None
                self.status = ('cancelled' if isinstance(error, OperationCancelled) else 'failed') if error else 'completed'
                self.completed_at_ns = time.perf_counter_ns()
                self.done.set()
        self.notify()
        return error

class WorkflowGroup:
    def __init__(self, stop=None, on_event=None):
        self.stop = stop if stop is not None else CancellationToken()
        self.handles = []
        self.on_event = on_event
        self.lock = threading.Lock()

    def add(self, handle):
        with self.lock:
            if self.stop.is_set(): raise OperationCancelled('Workflow cancelled')
            self.handles.append(handle)
        if self.on_event:
            def changed(h):
                from types import SimpleNamespace
                kind = 'started' if h.status == 'running' else 'finished' if h.done.is_set() else 'queued'
                self.on_event(SimpleNamespace(kind=kind,path=(h.action,),status=SimpleNamespace(value=h.status)))
            handle.subscribe(changed)

    def finish(self, failed=False):
        if failed: self.stop.set()
        with self.lock: handles = tuple(self.handles)
        first = None
        for handle in handles:
            try: handle.wait()
            except Exception as error:
                if first is None: first = error
                self.stop.set()
        if first: raise first
        if self.stop.is_set(): raise OperationCancelled('Workflow cancelled; confirm affected values with acquire')

@contextmanager
def assign_boundary():
    token = ATOMIC_ASSIGN.set(True)
    try: yield
    finally: ATOMIC_ASSIGN.reset(token)


def aggregate_handles(action, children, group=None):
    """One common handle for a scheduled set of parameter reads; no blocking worker wait."""
    batch = ExecutionHandle(action, None, group)
    batch.children = tuple(children)
    def changed(_=None):
        with batch._lock:
            if batch.done.is_set(): return
            if all(child.done.is_set() for child in batch.children):
                errors = [child.error for child in batch.children if child.error is not None]
                error = next((e for e in errors if not isinstance(e, OperationCancelled)), errors[0] if errors else None)
                batch.finish(error)
            else:
                batch.status = 'running' if any(child.status == 'running' for child in batch.children) else 'queued'
                batch.notify()
    for child in batch.children: child.subscribe(changed)
    changed()
    return batch
