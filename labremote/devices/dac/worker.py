import json
import time
from pathlib import Path
from uuid import uuid4
from labremote.runtime.device_worker import DeviceWorker
from labremote.runtime.monitor import ParameterMonitor
from labremote.runtime.jobs import CURRENT_JOB
from labremote.runtime.errors import OperationCancelled
from labremote.runtime.network import configure_client_timeout
from labremote.api.devices import DeviceAPI
from trap_dac.configuration import DeviceConfig
from trap_dac.model import atomic_json, load_preset
from trap_dac.sequence import load_sequence, save_sequence


class DACWorker(DeviceWorker):
    family='dac'
    def __init__(self):
        super().__init__()
        self.owner=uuid4().hex;self.description=None;self.ui_alive=time.monotonic()

    def make_monitor(self):return ParameterMonitor(self,())

    def identify(self):
        info=self.raw_device.describe_dac()
        if info.get('protocol')!=1:raise ValueError('Unsupported DAC API')
        configure_client_timeout(self.cli,2)
        self.description=info
        # Connecting explicitly opens USB, never initializes or sets voltage.
        self.run_remote('connect',{})
        return self.description

    def refresh(self):
        self.description=self.raw_device.describe_dac()
        self.publish_snapshot(self.description,'DAC_STATE')
        return self.description

    def run_remote(self,action,payload):
        from labremote.data_paths import DATA_ROOT
        handle=CURRENT_JOB.get()
        request_id=handle.request_id if handle else uuid4().hex
        if action in ('initialize','apply','step','sequence'):
            if not self.description:raise RuntimeError('Connect DAC first')
            payload={**payload,'fingerprint':self.description['fingerprint']}
        # Immutable JSON snapshot; UI edits cannot mutate an in-flight operation.
        payload=json.loads(json.dumps(payload,allow_nan=False))
        chamber=self.description['device']
        folder=DATA_ROOT/'dac'/chamber/'runs'/request_id
        atomic_json(folder/'request.json',dict(action=action,payload=payload,configuration=self.description['configuration']))
        state=None;stop_sent=False;last_heartbeat=time.monotonic();last_row=-1
        try:
            state=self.raw_device.start_dac_job(self.owner,request_id,action,payload)
            while state['status']=='running':
                if handle and handle.cancelled() and not stop_sent:
                    self.raw_device.stop_dac_job(self.owner,request_id);stop_sent=True
                now=time.monotonic()
                # A surviving worker must NOT keep a frozen/closed GUI's lease alive.
                if now-last_heartbeat>=1 and now-self.ui_alive<2.5 and not self._closing and not stop_sent:
                    state=self.raw_device.dac_heartbeat(self.owner,request_id);last_heartbeat=now
                else:state=self.raw_device.dac_job_status(request_id)
                self.task_progress.emit('DAC',state)
                if state.get('row',0)!=last_row:
                    last_row=state.get('row',0);atomic_json(folder/'progress.json',state)
                if state['status']=='running':time.sleep(.5)
            self.description=state.get('result') or self.raw_device.describe_dac()
            self.description['active_job']=None
            self.publish_snapshot(self.description,'DAC_STATE')
            if state['status']=='failed':raise RuntimeError(state['error'])
            if state['status']=='stopped':raise OperationCancelled('DAC stopped: '+(state.get('reason') or state.get('error') or 'user stop'))
            return state
        except Exception:
            # Do not replay a start/write after an ambiguous timeout. Server lease
            # expires even if a best-effort Stop cannot be delivered.
            if state is None or state.get('status')=='running':
                self.connection_error=True
            raise
        finally:
            atomic_json(folder/'client_result.json',state or dict(status='unknown',job_id=request_id,
                reason='No reply; do not retry output. Reconnect to inspect server job.'))

    def disconnect_device(self):
        if self.raw_device is not None:self.run_remote('disconnect',{})
        super().disconnect_device()

    def enqueue(self,handle):
        # Reject conflicting manual actions, rather than applying stale queued edits.
        if handle.action.startswith('DAC_') and self.has_requests():
            handle.finish(RuntimeError('DAC busy; request was not queued'))
            return handle
        return super().enqueue(handle)


class DACAPI(DeviceAPI):
    def _job(self,action,payload):
        snapshot=json.loads(json.dumps(payload,allow_nan=False))
        return self._submit('DAC_'+action.upper(),lambda w:w.run_remote(action,snapshot),arguments=snapshot)

    def initialize(self,initial_voltages=None,*,use_ldac=True):
        return self._job('initialize',dict(voltages=initial_voltages,use_ldac=use_ldac))

    def apply(self,voltages,*,use_ldac=True,manual_timing=None,name='Manual',notes=''):
        if hasattr(voltages,'by_id'):voltages=voltages.by_id
        return self._job('apply',dict(voltages=voltages,use_ldac=use_ldac,manual_timing=manual_timing or {},name=name,notes=notes))

    def set_voltage(self,electrode,voltage,*,use_ldac=True):
        values=(self.worker.description or {}).get('last_sent')
        if values is None:raise RuntimeError('No complete sent state; initialize or apply a full set first')
        if electrode not in values:raise ValueError('Unknown electrode')
        return self.apply({**values,electrode:voltage},use_ldac=use_ldac)

    def step(self,voltages,step,direction,*,electrode_id=None,component=None,use_ldac=True,manual_timing=None):
        return self._job('step',dict(voltages=voltages,step=step,direction=direction,electrode_id=electrode_id,
            component=component,use_ldac=use_ldac,manual_timing=manual_timing or {}))

    def configuration(self):
        if not self.worker.description:raise RuntimeError('Connect DAC first')
        return DeviceConfig.from_dict(self.worker.description['configuration'])

    def load_preset(self,path):return load_preset(path,self.configuration())

    def save_preset(self,path,voltages,*,name='Preset',notes=''):
        from trap_dac.model import VoltageSet
        state=VoltageSet.from_values(self.configuration(),voltages,name=name,notes=notes)
        atomic_json(path,state.as_dict())
        return state

    def load_sequence(self,path,*,use_ldac=True):return load_sequence(path,self.configuration(),use_ldac=use_ldac)

    def create_sequence(self,rows,*,name='Sequence',use_ldac=True):
        from trap_dac.model import VoltageSet
        from trap_dac.sequence import SequenceRow, VoltageSequence
        cfg=self.configuration()
        return VoltageSequence(cfg,tuple(SequenceRow(VoltageSet.from_values(cfg,row['voltages']),row['hold_s']) for row in rows),use_ldac,name).validate()

    def save_sequence(self,path,sequence):return save_sequence(path,sequence)

    def run_sequence(self,sequence,*,use_ldac=True,sequence_options=None):
        if isinstance(sequence,(str,Path)):sequence=self.load_sequence(sequence,use_ldac=use_ldac)
        return self._job('sequence',dict(sequence=sequence.as_dict() if hasattr(sequence,'as_dict') else sequence,
            sequence_options=sequence_options or {}))

    def reload_configuration(self):return self._job('reload_config',{})

    def cancel(self):self.worker.cancel_pending()

    def status(self):return self.refresh()
