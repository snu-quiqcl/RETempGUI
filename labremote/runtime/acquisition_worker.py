from labremote.runtime.device_worker import DeviceWorker
from labremote.runtime.io import acquire
from PyQt5 import QtCore


class AcquisitionWorker(DeviceWorker):
    repeat_method = 'read_waveforms'
    waveform_changed=QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        from labremote.runtime.waveform_runner import WaveformRunner
        self.waveform_runner=WaveformRunner(self,self.repeat_method)

    def cancel_pending(self):
        self.waveform_runner.suspend()
        super().cancel_pending()

    def _disconnect(self):
        self.waveform_runner.suspend()
        super()._disconnect()

    def connect_device(self,*args):
        super().connect_device(*args)
        with self._lock:self.waveform_runner.suspended=False

    def run(self):
        try:super().run()
        finally:
            self.waveform_runner.cancel()
            self.waveform_runner.join()

