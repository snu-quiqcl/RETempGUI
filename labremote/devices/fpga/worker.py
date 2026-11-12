from labremote.runtime.acquisition_worker import AcquisitionWorker
from labremote.runtime.parameters import DeviceProxy


class FPGAWorker(AcquisitionWorker):
    family='fpga'
    repeat_method='measure_repeated'

    def __init__(self, name='fpga_local'):
        from .mapping import load_profile
        self.profile = load_profile(name)
        self._fpga_owner = None
        self._disconnecting = False
        self._claimed_port = None
        super().__init__()
        self.name = name
        from labremote.runtime.motor_scan_runner import MotorScanRunner
        self.scan_runners={number:MotorScanRunner(self,number) for number in range(1,5)}
        from labremote.characterization.runner import FluorescenceRunner
        self.fluorescence_runner=FluorescenceRunner(self)
        from labremote.characterization.rabi_runner import RabiRunner
        self.rabi_runner=RabiRunner(self)
        from labremote.characterization.pulse_runner import PulseRunner
        from labremote.decay.runner import DecayRunner
        self.decay_runner=DecayRunner(self)
        from labremote.hom.runner import HOMRunner
        self.hom_runner=HOMRunner(self)
        from labremote.phase_shifter.runner import PhaseShifterRunner
        self.phase_shifter_runner=PhaseShifterRunner(self)
        from labremote.ion_check.runner import IonCheckRunner
        self.ion_check_runner=IonCheckRunner(self)
        from labremote.entanglement.runner import EntanglementRunner
        self.entanglement_runner=EntanglementRunner(self)
        from labremote.micromotion.runner import MicromotionRunner
        self.micromotion_runner=MicromotionRunner(self)
        self.ramsey_runner=PulseRunner(self,'ramsey');self.spam_runner=PulseRunner(self,'spam');self.initialization_runner=PulseRunner(self,'initialization')

    def reserve_fpga(self, owner):
        with self._lock:
            if self._disconnecting or self._closing or self.ps is None or self.connection_error:
                raise ConnectionError('FPGA is not connected: '+self.name)
            if self._fpga_owner is owner:return
            if self._fpga_owner is not None or self.has_foreground_requests():
                raise RuntimeError('FPGA is occupied: '+self.name)
            self._fpga_owner=owner
            reads=[h for h in [self._active,*self._pending]
                   if h is not None and not h.done.is_set() and getattr(h,'automatic_monitor',False)]
        owner.remember(self)
        # Reserve before draining: a new UI poll cannot slip into the gap.
        # Wait outside the worker lock so the serial FIFO can finish its read.
        try:
            for handle in reads:
                try:handle.wait()
                except Exception as exc:raise ConnectionError('FPGA status refresh failed before experiment: '+str(exc)) from exc
            with self._lock:
                if self._disconnecting or self._closing or self.ps is None or self.connection_error:
                    raise ConnectionError('FPGA connection unavailable after status refresh: '+self.name)
        except BaseException:
            self.release_fpga(owner)
            raise

    def release_fpga(self, owner):
        with self._lock:
            if self._fpga_owner is owner:self._fpga_owner=None

    def enqueue(self,handle):
        from .mapping import CURRENT, FROZEN
        from labremote.runtime.errors import OperationCancelled
        with self._lock:
            owner=getattr(handle.group,'owner',None)
            if self._fpga_owner is not None and owner is not self._fpga_owner and handle.action != 'DISCONNECT':
                if getattr(handle,'automatic_monitor',False):
                    # Best-effort UI read; never inject it into an owned experiment.
                    self._monitor_pending.discard(handle.monitor_key)
                    handle.finish();return handle
                handle.finish(RuntimeError('FPGA is occupied: '+self.name))
                return handle
            if self._disconnecting and handle.action not in ('DISCONNECT',):
                # Cleanup emitted by a cancelled runner must still be admitted.
                cleanup_groups = [getattr(t, attr, None) for t in self._background_tasks for attr in ('cleanup_group', 'fpga_cleanup_group')]
                if handle.group is None or handle.group not in cleanup_groups:
                    handle.finish(OperationCancelled('FPGA is disconnecting'))
                    return handle
            state = CURRENT.get()
            handle.fpga_mapping = state if state is not None and state[0].device_id == self.profile.device_id else (FROZEN.get().get(self.profile.device_id, self.profile), None)
            # Admission and ownership use the same lock, including FIFO insertion.
            from labremote.runtime.characterization_guard import enqueue
            return enqueue(self,handle,super().enqueue)

    def execute(self, handle):
        from .mapping import scope
        with scope(*handle.fpga_mapping):
            result = super().execute(handle)
            import serial
            error = handle.error
            seen = set()
            while error is not None and id(error) not in seen:
                seen.add(id(error))
                if isinstance(error, serial.SerialException):
                    self.connection_error = True
                    self._disconnect()
                    self.disconnected.emit('USB/serial disconnected; sequencer STOP and output cleanup unconfirmed')
                    break
                error = error.__cause__ or error.__context__
            return result

    def update_profile(self, profile):
        from .mapping import save_profile
        with self._lock:
            if profile.device_id != self.profile.device_id:
                raise ValueError('Cannot change FPGA identity')
            if self._closing or self._disconnecting or self._fpga_owner is not None or self.waveform_runner.running() or self.has_foreground_requests() or any(t.running() for t in self._background_tasks):
                raise RuntimeError('Stop FPGA jobs before changing mapping')
            if self.ps is not None and profile.document()['pins'] != self.profile.document()['pins']:
                raise RuntimeError('Disconnect before changing board pin names')
            save_profile(profile)
            self.profile = profile

    def _disconnect(self):
        from .registry import release_port
        try:
            super()._disconnect()
        finally:
            release_port(self)
            self._claimed_port = None

    def disconnect_device(self):
        error = None
        try:
            # Do not reset all outputs: experiment cleanup defines final levels.
            if self.raw_device is not None:
                self.raw_device.controller.device.stop_sequencer()
        except Exception as exc:
            error = exc
        finally:
            self._disconnect()
            self._disconnecting = False
        if error is not None:
            raise ConnectionError('Disconnected; STOP/output state unconfirmed: ' + str(error)) from error
        self.disconnected.emit('Disconnected after STOP; outputs retain experiment cleanup / last manual levels')

    def request_disconnect(self):
        import threading
        from labremote.runtime.jobs import ExecutionHandle
        from labremote.api.devices import DeviceAPI
        with self._lock:
            if self._disconnecting:
                return self._disconnect_handle
            self._disconnecting = True
            result = self._disconnect_handle = ExecutionHandle('DISCONNECT', None)
            tasks = tuple(self._background_tasks)
            owner=self._fpga_owner
            cancellation=getattr(owner,'cancellation',None)
            if cancellation is not None:cancellation.set()
        self.cancel_pending()

        def finish():
            try:
                for task in tasks:
                    task.join()
                if cancellation is not None:owner.released.wait()
                DeviceAPI(self)._submit('DISCONNECT', lambda w: w.disconnect_device()).wait()
                result.finish()
            except Exception as exc:
                result.finish(exc)
            finally:
                self._disconnecting = False
        self._disconnect_thread = threading.Thread(target=finish, name='disconnect-' + str(self.name), daemon=True)
        self._disconnect_thread.start()
        return result

    def make_monitor(self):
        from .monitor import Monitor
        return Monitor(self)

    def connect_device(self, serial_port, unused_port, name):
        if name != self.profile.device_id:
            raise ValueError('FPGA device ID does not match its profile')
        self._disconnect();self.name=name
        from .registry import claim_port
        self._disconnecting = False
        claim_port(serial_port, self)
        self._claimed_port = serial_port
        self._execution_device=('serial',serial_port,name)
        from .adapter import FPGAAdapter
        raw=FPGAAdapter()
        try:raw.controller.connect(serial_port)
        except Exception:
            raw.disconnect()
            self._disconnect()
            raise
        self.cli=self.raw_device=raw
        self.ps=DeviceProxy(raw,self._execution_device,self.family)
        self.connection_error=self._timed_out=False
        self.waveform_runner.suspended=False
        self.monitor.register_parameters()
        self.connected.emit({'idn':'Local Arty FPGA','port':serial_port})

