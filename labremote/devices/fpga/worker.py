from labremote.runtime.acquisition_worker import AcquisitionWorker
from labremote.runtime.parameters import DeviceProxy


class FPGAWorker(AcquisitionWorker):
    family='fpga'
    repeat_method='measure_repeated'

    def __init__(self):
        super().__init__()
        from labremote.runtime.motor_scan_runner import MotorScanRunner
        self.scan_runners={number:MotorScanRunner(self,number) for number in range(1,5)}
        from labremote.characterization.runner import FluorescenceRunner
        self.fluorescence_runner=FluorescenceRunner(self)

    def enqueue(self,handle):
        from labremote.runtime.workflow_runner import _TASK_LOCK
        with _TASK_LOCK:
            runner=self.fluorescence_runner
            if runner.running() and handle.group is not runner.group and handle.action!='DISCONNECT':
                error=RuntimeError('FPGA reserved by fluorescence')
                if handle.group is not None:handle.group.stop.set()
                handle.finish(error);self.handle_changed.emit(handle)
                return handle
            return super().enqueue(handle)

    def make_monitor(self):
        from .monitor import Monitor
        return Monitor(self)

    def connect_device(self, serial_port, unused_port, name):
        self._disconnect();self.name=name
        self._execution_device=('serial',serial_port,name)
        from .adapter import FPGAAdapter
        raw=FPGAAdapter()
        try:raw.controller.connect(serial_port)
        except Exception:
            raw.disconnect();raise
        self.cli=self.raw_device=raw
        self.ps=DeviceProxy(raw,self._execution_device,self.family)
        self.connection_error=self._timed_out=False
        self.waveform_runner.suspended=False
        self.monitor.register_parameters()
        self.connected.emit({'idn':'Local Arty FPGA','port':serial_port})

    def execute(self, handle):
        super().execute(handle)
        if isinstance(handle.error,TimeoutError):
            self.connection_error=True
            self._disconnect()
            self.disconnected.emit('FPGA serial timeout: reconnect explicitly; verify hardware state')
