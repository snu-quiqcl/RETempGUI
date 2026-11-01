"""Best-effort UI polling: one read per endpoint, no parameter backlog."""
from contextlib import contextmanager
import threading
import time
import weakref


def endpoint(worker):
    identity = getattr(worker, '_execution_device', None)
    if not identity: return None
    # Local serial devices must not share the remote InstrumentServer budget.
    return tuple(identity) if identity[0] == 'serial' else tuple(identity[:2])


class AutoMonitor:
    gap_s = .5

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.workers = weakref.WeakSet()
        self.pending = weakref.WeakKeyDictionary()
        self.active = {}
        self.next_at = {}
        self.blocked = set()
        self.failed_workers = weakref.WeakSet()
        self.workflows = 0
        self.timer = None

    def register(self, worker):
        with self.lock: self.workers.add(worker)

    def request(self, worker, read=None):
        with self.lock:
            if worker._closing or worker.connection_error or getattr(worker, "io_fault", False) or worker.ps is None: return
            if endpoint(worker) in self.blocked or worker in self.failed_workers: return
            self.pending[worker] = read  # Coalesce repeated timer ticks, never append reads.
        self._ensure_timer()

    def _ensure_timer(self):
        from PyQt5 import QtCore
        app = QtCore.QCoreApplication.instance()
        if self.timer is None and app and QtCore.QThread.currentThread() == app.thread():
            self.timer = QtCore.QTimer(app)
            self.timer.setInterval(200)
            self.timer.timeout.connect(self.tick)
            self.timer.start()

    @contextmanager
    def workflow(self):
        with self.lock: self.workflows += 1
        try: yield
        finally:
            with self.lock: self.workflows -= 1

    def timed_out(self, worker):
        """Called for any operation timeout, before observers can dispatch another read."""
        key = endpoint(worker)
        if key is None: return
        with self.lock:
            self.blocked.add(key)
            for candidate in list(self.pending):
                if endpoint(candidate) == key: self.pending.pop(candidate, None)

    def reconnected(self, worker):
        with self.lock:
            key = endpoint(worker)
            self.blocked.discard(key)
            self.failed_workers.discard(worker)
            self.next_at[key] = self.clock() + self.gap_s

    def foreground_busy(self):
        if self.workflows: return True
        for worker in list(self.workers):
            repeat = getattr(worker, 'waveform_runner', None)
            if repeat is not None and repeat.running(): return True
            if any(task.running() for task in tuple(worker._background_tasks)): return True
            with worker._lock:
                handles = [*worker._pending, worker._active]
                if any(h is not None and not h.done.is_set() and not getattr(h, 'automatic_monitor', False) for h in handles):
                    return True
        return False

    def permitted(self, worker):
        with self.lock:
            return (not worker._closing and not worker.connection_error and not getattr(worker, "io_fault", False) and worker.ps is not None
                    and endpoint(worker) not in self.blocked and not self.foreground_busy())

    def tick(self):
        with self.lock:
            for key, (ref, handle) in list(self.active.items()):
                if not handle.done.is_set(): continue
                del self.active[key]
                self.next_at[key] = self.clock() + self.gap_s
                worker = ref()
                if handle.error and worker is not None:
                    if isinstance(handle.error, TimeoutError) or 'Server did not reply before timeout' in str(handle.error):
                        if not getattr(handle, 'auto_monitor_timeout_latched', False): self.timed_out(worker)
                    else:
                        self.failed_workers.add(worker)
                        self.pending.pop(worker, None)
            if self.foreground_busy(): return
            for worker in list(self.pending):
                key = endpoint(worker)
                if worker._closing or worker.connection_error or getattr(worker, "io_fault", False) or worker.ps is None or key in self.blocked:
                    self.pending.pop(worker, None)
                    continue
                if key in self.active or self.clock() < self.next_at.get(key, 0): continue
                if worker.has_requests(): continue
                read = self.pending[worker]
                try:
                    if read is None:
                        handles = worker.monitor.scan(limit=1, automatic=True)
                    else:
                        from .jobs import ExecutionHandle
                        from .runner import OperationRunner
                        handle = ExecutionHandle(read[0], read[1])
                        handle.automatic_monitor = True
                        OperationRunner.submit(worker, handle)
                        handles = [handle]
                except Exception as exc:
                    self.pending.pop(worker, None)
                    self.failed_workers.add(worker)
                    worker.failure.emit('AUTO_MONITOR', str(exc))
                    continue
                # Round-robin between devices on the same server.
                self.pending.pop(worker, None)
                if handles:
                    if read is None: self.pending[worker] = None
                    self.active[key] = (weakref.ref(worker), handles[0])


AUTO_MONITOR = AutoMonitor()
