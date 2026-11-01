"""One repeating workflow per device, using the ordinary API and worker FIFO."""
import math
import threading
from contextlib import nullcontext
from labremote.runtime.jobs import ExecutionHandle, WorkflowGroup


class WaveformHandle(ExecutionHandle):
    def request_cancel(self):
        group_lock=getattr(self.group.stop,'lock',None)
        with group_lock if group_lock is not None else nullcontext():
            with self._lock:
                if self.done.is_set():return False
                self.cancel_event.set()
                self.group.stop.set()
                self.status='stopping'
        self.notify()
        return True

    def cancel(self):return self.request_cancel()


class WaveformRunner:
    def __init__(self,worker,method='read_waveforms'):
        self.worker=worker
        self.method=method
        self.label='WAVEFORM' if method=='read_waveforms' else 'TELEMETRY_LOOP'
        self.handle=None
        self._thread=None
        self.suspended=False

    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self,channels,interval_s,parent=None):
        worker=self.worker
        from labremote.runtime.workflow_runner import _TASK_LOCK
        with _TASK_LOCK, worker._lock:
            error=None
            if any(t.label=="MOTOR_SCAN" and t.running() for t in worker._background_tasks):error=RuntimeError("Stop motor scan before starting repeat measurement")
            elif any(getattr(t,'exclusive_fpga',False) and t.running() for t in worker._background_tasks):error=RuntimeError('FPGA reserved by daily characterization')
            elif self.running():error=RuntimeError('Waveform capture is already running or stopping')
            elif worker._closing or self.suspended or worker.connection_error or worker.ps is None:
                error=ConnectionError('Connect the device before starting waveform capture')
            elif isinstance(interval_s,bool) or not isinstance(interval_s,(int,float)) or not math.isfinite(interval_s) or interval_s<0:
                error=ValueError('Waveform interval must be a finite nonnegative number')
            try:channels=(channels,) if isinstance(channels,str) else tuple(channels)
            except TypeError:error=ValueError('Select supported acquisition channels')
            group=WorkflowGroup(stop=parent.stop if parent is not None else None)
            handle=WaveformHandle(self.label,None,group=group)
            if parent is not None:parent.add(handle)
            if error is not None:
                if parent is not None:parent.stop.set()
                handle.finish(error)
                worker.failure.emit(self.label,str(error))
                return handle
            # Freeze a mutable channel selection before another thread uses it.
            group.waveform_run_id=handle.request_id
            self.handle=handle
            handle.subscribe(lambda h:worker.waveform_changed.emit(h))
            self._thread=threading.Thread(target=self._run,args=(handle,channels,interval_s),name='waveform-'+str(worker.name))
            self._thread.start()
            return handle

    def cancel(self):
        handle=self.handle
        if handle is not None:handle.request_cancel()
        return handle

    def suspend(self):
        with self.worker._lock:
            self.suspended=True
            self.cancel()

    def join(self):
        thread=self._thread
        if thread is not None and thread is not threading.current_thread():thread.join()

    def _run(self,handle,channels,interval_s):
        from labremote.api.devices import device_api
        api=device_api(self.worker,group=handle.group)
        error=None
        child_failed=False
        try:
            with handle._lock:
                handle.check_cancelled()
                handle.status='running'
            handle.notify()
            while True:
                handle.check_cancelled()
                child=getattr(api,self.method)(channels)
                try:
                    child.wait()
                except Exception:
                    child_failed=True
                    raise
                finally:
                    # Do not retain every waveform/handle during an indefinite run.
                    with handle.group.lock:handle.group.handles.remove(child)
                handle.check_cancelled()
                if handle.group.stop.wait(interval_s):handle.check_cancelled()
        except Exception as exc:
            error=exc
            handle.group.stop.set()
        finally:
            error=handle.finish(error)
            # Child errors already produce the common runner's one alarm.
            if error is not None and not child_failed:
                self.worker.failure.emit(self.label,f'{type(error).__name__}: {error}\nRequest: {handle.request_id}')
