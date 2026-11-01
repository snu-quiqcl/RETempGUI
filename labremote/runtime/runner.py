"""Shared operation lifecycle runner. Invoked only on the owning worker thread."""
from labremote.runtime.jobs import CURRENT_JOB
from labremote.runtime.ownership import DEFAULT_MANAGER, CURRENT_OWNER
from labremote.runtime.errors import OperationCancelled
from labremote.runtime.parameters import DeviceProxy

class OperationRunner:
    @staticmethod
    def submit(worker, handle):
        if handle.group is not None: handle.group.add(handle)
        return worker.enqueue(handle)

    @staticmethod
    def execute(worker, handle):
        self = worker
        from labremote.config.device_config import operation_config
        error = None
        result = None
        session = None
        record = None
        token = CURRENT_JOB.set(handle)
        runner_token = None
        record_token = None
        handle.status = 'running'
        handle.notify()
        self.handle_changed.emit(handle)
        self.busy_changed.emit(True)
        ramp = handle.action in ('OUTPUT', 'SET_POWER')
        if ramp: self.ramp_active.emit(True)
        try:
            handle.check_cancelled()
            if getattr(handle, 'automatic_monitor', False):
                from .auto_monitor import AUTO_MONITOR
                if not AUTO_MONITOR.permitted(self): return
            if handle.action not in ('CONNECT', 'DISCONNECT') and (self.connection_error or self.ps is None):
                raise ConnectionError('Device connection unavailable; connect explicitly')
            with operation_config():
                if not handle.action.startswith('MONITOR'):
                    from labremote.runtime.recording import RunRecord, CURRENT_RECORD, log_value
                    from labremote.config.device_config import load_device_config
                    record = RunRecord(handle.action, {'request_id':handle.request_id, 'device':str(self._execution_device), 'config':load_device_config(self.family, self.name or ''), 'parameters':log_value(handle.arguments)})
                    record_token = CURRENT_RECORD.set((record, lambda message: self.failure.emit('LOG', message)))
                identity = self._execution_device or ('unconnected', id(self))
                session = DEFAULT_MANAGER.acquire({identity})
                runner_token = CURRENT_OWNER.set(session)
                if self.raw_device is not None:
                    self.ps = DeviceProxy(self.raw_device, self._execution_device, self.family)
                result = handle.callback(self)
                handle.check_cancelled()
                self._timed_out = False
                if handle.action == 'CONNECT':
                    from .auto_monitor import AUTO_MONITOR
                    AUTO_MONITOR.reconnected(self)
        except Exception as exc:
            error = exc
            if handle.group is not None: handle.group.stop.set()
            timeout = isinstance(exc, TimeoutError) or 'Server did not reply before timeout' in str(exc)
            if timeout:
                from .auto_monitor import AUTO_MONITOR
                AUTO_MONITOR.timed_out(self)
                handle.auto_monitor_timeout_latched = True
                # The client already rebuilt the socket, without retrying the request.
                if getattr(self.cli, 'consecutive_timeouts', 2 if self._timed_out else 1) >= 2:
                    self.connection_error = True
                    self._disconnect()
                    self.disconnected.emit('Connection error: server did not respond after socket recreation')
                self._timed_out = True
            elif isinstance(exc, ConnectionError):
                self.connection_error = True
                self._disconnect()
                self.disconnected.emit(str(exc))
            if handle.action == 'CONNECT': self.connection_error = True
        finally:
            if runner_token is not None: CURRENT_OWNER.reset(runner_token)
            CURRENT_JOB.reset(token)
            if record_token is not None: CURRENT_RECORD.reset(record_token)
            if record is not None:
                try: record.finish(error=error)
                except Exception as logging_error:
                    self.failure.emit('LOG', str(logging_error))
            previous_error = error
            def finalized(final_error):
                if final_error is not None and handle.group is not None: handle.group.stop.set()
                if session: session.release()
                if record is not None and final_error is not previous_error:
                    try: record.finish(error=final_error)
                    except Exception as logging_error: self.failure.emit('LOG', str(logging_error))
            # Retire deduplication before completion observers can schedule another scan.
            # Do not discard it later in the worker loop: a new request may own the same key.
            with self._lock:
                self._monitor_pending.discard(handle.monitor_key)
            error = handle.finish(error, before_publish=finalized, result=result)
            self.handle_changed.emit(handle)
            if error:
                self.failure.emit(handle.action, f'{type(error).__name__}: {error}\nAcquire affected values to confirm. Request: {handle.request_id}')
            else: self.completed.emit(handle.action)
            if ramp: self.ramp_active.emit(False)
            self.busy_changed.emit(False)

