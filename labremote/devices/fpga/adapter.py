"""Local serial hardware exposed as parameters for the common acquire/assign path."""
from types import SimpleNamespace
from labremote.devices.fpga.controller import Controller, OUTPUTS
from labremote.runtime.jobs import CURRENT_JOB, ATOMIC_ASSIGN


class Cancellation:
    def is_set(self):
        job=CURRENT_JOB.get()
        return job is not None and not ATOMIC_ASSIGN.get() and job.cancelled()


class Parameter:
    def __init__(self, getter, setter=None):self.getter,self.setter=getter,setter
    def get(self):return self.getter()
    def set(self, value):
        if self.setter is None:raise ValueError('Read-only parameter')
        return self.setter(value)


class FPGAAdapter:
    def __init__(self, controller=None):
        self.controller=controller or Controller()
        self.channel_value=0;self.exposure_value=100.;self.last_outputs={}
        self.states=Parameter(self.controller.states)
        self.channel=Parameter(lambda:self.channel_value,lambda v:setattr(self,'channel_value',v))
        self.exposure_ms=Parameter(lambda:self.exposure_value,lambda v:setattr(self,'exposure_value',v))
        self.average_value=1
        self.average=Parameter(lambda:self.average_value,lambda v:setattr(self,'average_value',v))
        self.measurement=Parameter(self.measure)
        self._sequence_request=None;self._sequence_pending=False;self._sequence_result=None;self._sequence_error=None
        self.sequence_request=Parameter(lambda:self._sequence_request,self.set_sequence_request)
        self.sequence_result=Parameter(self.run_sequence)
        self.outputs=SimpleNamespace(**{name:Parameter(lambda n=name:self.read_output(n),lambda v,n=name:self.set_output(n,v)) for name in OUTPUTS})

    def measure(self):
        from labremote.runtime.errors import OperationCancelled
        try:return self.controller.measure(self.channel_value,self.exposure_value,Cancellation())
        except InterruptedError as exc:raise OperationCancelled(str(exc)) from exc

    def read_output(self, name):
        # Slow-port outputs cannot be physically read back; remain unknown.
        return self.controller.states()[name]

    def set_output(self, name, value):
        return self.controller.set_output(name,value,Cancellation())

    def disconnect(self):self.controller.disconnect()

    def set_sequence_request(self,value):
        from .sequence_file import validate_request
        self._sequence_request=validate_request(**value)
        self._sequence_owner=CURRENT_JOB.get()
        self._sequence_pending=True;self._sequence_result=None;self._sequence_error=None

    def run_sequence(self):
        from labremote.runtime.errors import OperationCancelled
        if self._sequence_pending:
            self._sequence_pending=False  # No retry through a repeated read.
            owner=self._sequence_owner
            self._sequence_owner=None
            if owner is not CURRENT_JOB.get() or (owner is not None and owner.cancelled()):
                self._sequence_error=OperationCancelled('Sequence request belongs to a cancelled or different operation')
                raise self._sequence_error
            try:self._sequence_result=self.controller.run_sequence_file(self._sequence_request,Cancellation())
            except InterruptedError as exc:
                self._sequence_error=OperationCancelled(str(exc))
            except Exception as exc:self._sequence_error=exc
        if self._sequence_error is not None:raise self._sequence_error
        if self._sequence_result is None:raise RuntimeError('Submit a sequence_request first')
        return self._sequence_result
