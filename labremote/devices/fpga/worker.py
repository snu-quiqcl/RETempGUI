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
        from labremote.characterization.rabi_runner import RabiRunner
        self.rabi_runner=RabiRunner(self)
        from labremote.characterization.pulse_runner import PulseRunner
        self.ramsey_runner=PulseRunner(self,'ramsey');self.spam_runner=PulseRunner(self,'spam');self.initialization_runner=PulseRunner(self,'initialization')

    def enqueue(self,handle):
        from labremote.runtime.characterization_guard import enqueue
        return enqueue(self,handle,super().enqueue)

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
