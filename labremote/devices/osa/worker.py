from labremote.runtime.acquisition_worker import AcquisitionWorker
from labremote.runtime.io import acquire
from labremote.runtime.network import configure_client_timeout
from labremote.config.device_config import load_device_config


class SpectrumParameter:
    def __init__(self, raw):self.raw=raw
    def get(self):
        # Paired wire payload is decoded and validated by acquire's registry policy.
        return {'x':self.raw.trace_x.get(),'y':self.raw.trace_y.get()}


class OSAProxy:
    def __init__(self, raw):
        self.raw=raw;self.spectrum=SpectrumParameter(raw)
    def __getattr__(self, name):return getattr(self.raw,name)


class OSAWorker(AcquisitionWorker):
    family='osa'
    repeat_method='read_spectrum'

    def __init__(self):
        super().__init__()
        self._feedback_frame=None

    def execute(self,handle):
        super().execute(handle)
        if handle.action=='SPECTRUM' and handle.error is None and handle.arguments.get('waveform_run_id'):
            import time
            from copy import deepcopy
            with self._lock:self._feedback_frame=dict(run_id=handle.arguments['waveform_run_id'],request_id=handle.request_id,acquired_at=time.monotonic(),spectrum=deepcopy(handle.result))

    def feedback_snapshot(self,include_spectrum=True):
        from copy import deepcopy
        with self._lock:
            handle=self.waveform_runner.handle
            active=self.ps is not None and not self.connection_error and self.waveform_runner.running() and handle is not None and not handle.cancelled() and not handle.done.is_set()
            frame=self._feedback_frame
            if frame is not None and not include_spectrum:frame={k:v for k,v in frame.items() if k!='spectrum'}
            return dict(active=active,run_id=handle.request_id if handle is not None else None,frame=deepcopy(frame))

    def _disconnect(self):
        with self._lock:self._feedback_frame=None
        super()._disconnect()

    def make_monitor(self):
        from .monitor import Monitor
        return Monitor(self)

    def prepare_device(self, raw):return OSAProxy(raw)

    def identify(self):
        acquire(self.ps.client_operation_version)
        acquire(self.ps.connected)
        # OSA sweeps may take longer than the standard RF request timeout.
        seconds=max(acquire(self.ps.io_timeout_s)+5,load_device_config('osa',self.name)['acquisition']['timeout_s'])
        configure_client_timeout(self.cli,seconds)
        return {'idn':acquire(self.ps.identity)}
