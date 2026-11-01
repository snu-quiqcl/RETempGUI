"""Library registration and deduplicated 60-second monitoring for every worker."""
import time
from labremote.runtime.jobs import ExecutionHandle
from labremote.runtime.parameters import LIBRARY
from labremote.runtime.io import acquire

class ParameterMonitor:
    def __init__(self, worker, paths):
        self.worker = worker
        self.paths = tuple(paths)

    def register_parameters(self):
        """Register missing observations without reading hardware or replacing valid values."""
        states = LIBRARY.snapshot()
        for path in self.paths:
            key = (self.worker._execution_device, path)
            if key not in states:
                LIBRARY.update(key, quality='unknown')

    def scan(self, *, group=None, limit=None, automatic=False):
        worker = self.worker
        with worker._lock:
            if worker._closing or worker.connection_error or worker.ps is None: return []
            from labremote.config.paths import registry_paths
            from labremote.runtime.parameters import ParameterRegistry
            policy = ParameterRegistry(registry_paths())
            states = LIBRARY.snapshot()
            result = []
            for (identity, path), state in states.items():
                if identity != worker._execution_device or path in worker._monitor_pending: continue
                spec = policy.get(worker.family, path)
                if not spec.readable or not spec.monitor: continue
                if state.observed_at and time.monotonic() - state.observed_at < 60: continue
                def read(w, path=path):
                    parameter = w.ps
                    for part in path.split('.'): parameter = getattr(parameter, part)
                    acquire(parameter)
                handle = ExecutionHandle('MONITOR ' + path, read, group=group, monitor_key=path)
                handle.automatic_monitor = automatic
                worker._monitor_pending.add(path)
                from labremote.runtime.runner import OperationRunner
                try: OperationRunner.submit(worker, handle)
                except Exception:
                    worker._monitor_pending.discard(path)
                    raise
                result.append(handle)
                if limit is not None and len(result)>=limit:break
            return result

