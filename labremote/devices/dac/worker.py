"""Client-side electrode mapping and sequence execution for DAC API v2."""
import hashlib
import json
import time
from pathlib import Path
from labremote.runtime.device_worker import DeviceWorker
from labremote.runtime.monitor import ParameterMonitor
from labremote.runtime.errors import OperationCancelled
from labremote.runtime.network import configure_client_timeout
from labremote.api.devices import DeviceAPI
from labremote.config.dac import DeviceConfig, load_config, DEFAULT_CONFIG_DIR, resolve_configuration_path
from labremote.devices.dac.model import load_preset, atomic_json
from labremote.devices.dac.sequence import load_sequence, save_sequence


class DACWorker(DeviceWorker):
    family='dac'

    def __init__(self):
        super().__init__()
        self.description=None
        self.ui_alive=time.monotonic()
        self.config_path=None
        self.config=None
        self.configuration_id=None
        self.control_token=None

    def make_monitor(self):return ParameterMonitor(self,())

    def load_configuration(self,path=None):
        if path is None:
            path=self.config_path
        if path is None:
            chamber='EA' if 'ea' in self.name.lower() else 'EC'
            path=DEFAULT_CONFIG_DIR/(chamber+'.local.json')
        path=resolve_configuration_path(path)
        config=load_config(path)
        self.config_path=Path(path)
        self.config=config
        self.configuration_id=None
        return config

    def _description(self,status,adopt=False):
        offsets=[[float(v) for v in row] for row in self.config.offsets]
        digest=hashlib.sha256(json.dumps(offsets,separators=(',', ':')).encode()).hexdigest()
        remote_offsets=status.get('calibration_offsets')
        compatible=(remote_offsets==offsets if remote_offsets is not None else status.get('calibration_hash')==digest)
        if adopt:
            self.configuration_id=status.get('configuration_id') if compatible else None
        ready=bool(status.get('ready') and compatible and self.configuration_id
                   and self.configuration_id==status.get('configuration_id'))
        matrix=status.get('last_requested_voltages')
        values={e.id:matrix[e.chip][e.channel] for e in self.config.electrodes} if matrix is not None and ready else None
        reason=('USB recovery required' if status.get('faulted') else
                'Initialize required' if not status.get('ready') else
                'Calibration mismatch: load matching client calibration or explicitly initialize' if not compatible else
                'Ready (TX only)')
        self.description=dict(status,device=self.config.device,configuration=self.config.as_dict(),
                              ready=ready,last_sent=values,active_job=None,status_reason=reason)
        self.publish_snapshot(self.description,'DAC_STATE')
        return self.description

    def identify(self):
        if self.config is None:self.load_configuration()
        status=self.raw_device.get_status()
        if status.get('protocol')!=2:raise ValueError('DAC API v2 driver required; update server package')
        configure_client_timeout(self.cli,120)
        return self._description(self.raw_device.connect(),adopt=True)

    def refresh(self):
        return self._description(self.raw_device.get_status(),adopt=True)

    def synchronize(self):
        status=self.refresh()
        if not status.get('ready'):
            raise ValueError(status['status_reason'])
        return status

    def _check_cancelled(self,handle):
        if handle:handle.check_cancelled()
        if self._closing:raise OperationCancelled('DAC client is closing')
        if time.monotonic()-self.ui_alive>=2.5:
            raise OperationCancelled('DAC UI heartbeat stopped; no next row sent')

    def _apply(self,state,use_ldac,timing,reuse=False):
        from labremote.operation.dac.set_voltages import set_voltages
        return set_voltages(self,state,use_ldac,timing,reuse)

    def run_remote(self,action,payload):
        from labremote.operation.dac.execute import execute
        return execute(self,action,payload)

    def disconnect_device(self):
        # Disconnect this client only; other clients may use the same server driver.
        self.configuration_id=None
        super().disconnect_device()

    def enqueue(self,handle):
        from labremote.runtime.characterization_guard import enqueue
        return enqueue(self,handle,self._enqueue_unreserved)

    def _enqueue_unreserved(self,handle):
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
        return self._job('set_channel',dict(electrode=electrode,voltage=voltage,use_ldac=use_ldac))

    def step(self,voltages,step,direction,*,electrode_id=None,component=None,use_ldac=True,manual_timing=None):
        return self._job('step',dict(voltages=voltages,step=step,direction=direction,electrode_id=electrode_id,
            component=component,use_ldac=use_ldac,manual_timing=manual_timing or {}))

    def configuration(self):
        if not self.worker.description:raise RuntimeError('Connect DAC first')
        return DeviceConfig.from_dict(self.worker.description['configuration'])

    def load_preset(self,path):return load_preset(path,self.configuration())

    def save_preset(self,path,voltages,*,name='Preset',notes=''):
        from labremote.devices.dac.model import VoltageSet
        state=VoltageSet.from_values(self.configuration(),voltages,name=name,notes=notes)
        atomic_json(path,state.as_dict())
        return state

    def load_sequence(self,path,*,use_ldac=True):return load_sequence(path,self.configuration(),use_ldac=use_ldac)

    def create_sequence(self,rows,*,name='Sequence',use_ldac=True):
        from labremote.devices.dac.model import VoltageSet
        from labremote.devices.dac.sequence import SequenceRow, VoltageSequence
        cfg=self.configuration()
        return VoltageSequence(cfg,tuple(SequenceRow(VoltageSet.from_values(cfg,row['voltages']),row['hold_s']) for row in rows),use_ldac,name).validate()

    def save_sequence(self,path,sequence):return save_sequence(path,sequence)

    def run_sequence(self,sequence,*,use_ldac=True,sequence_options=None):
        if isinstance(sequence,(str,Path)):sequence=self.load_sequence(sequence,use_ldac=use_ldac)
        return self._job('sequence',dict(sequence=sequence.as_dict() if hasattr(sequence,'as_dict') else sequence,
            sequence_options=sequence_options or {}))

    def reload_configuration(self,path=None):return self._job('reload_config',dict(path=str(path) if path else None))

    def recover(self):return self._job('recover',{})

    def cancel(self):self.worker.cancel_pending()

    def status(self):return self.refresh()
