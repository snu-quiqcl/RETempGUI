"""Client-side electrode mapping and sequence execution for DAC API v2."""
import hashlib
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
from trap_dac.configuration import DeviceConfig, load_config
from trap_dac.model import atomic_json, load_preset, VoltageSet, step_set
from trap_dac.sequence import load_sequence, save_sequence, VoltageSequence
from trap_dac.timing import ManualTiming, SequenceOptions


class DACWorker(DeviceWorker):
    family='dac'

    def __init__(self):
        super().__init__()
        self.description=None
        self.ui_alive=time.monotonic()
        self.config_path=None
        self.config=None
        self.configuration_id=None

    def make_monitor(self):return ParameterMonitor(self,())

    def load_configuration(self,path=None):
        if path is None:
            path=self.config_path
        if path is None:
            chamber='EA' if 'ea' in self.name.lower() else 'EC'
            path=Path(__file__).resolve().parents[3]/'trap_dac/configs'/(chamber+'.local.json')
        config=load_config(path)
        self.config_path=Path(path)
        self.config=config
        self.configuration_id=None
        return config

    def _description(self,status,adopt=False):
        offsets=[list(row) for row in self.config.offsets]
        digest=hashlib.sha256(json.dumps(offsets,separators=(',', ':')).encode()).hexdigest()
        compatible=status.get('calibration_hash')==digest
        if adopt:
            self.configuration_id=status.get('configuration_id') if compatible else None
        ready=bool(status.get('ready') and compatible and self.configuration_id
                   and self.configuration_id==status.get('configuration_id'))
        matrix=status.get('last_requested_voltages')
        values={e.id:matrix[e.chip][e.channel] for e in self.config.electrodes} if matrix is not None and ready else None
        self.description=dict(status,device=self.config.device,configuration=self.config.as_dict(),
                              ready=ready,last_sent=values,active_job=None)
        self.publish_snapshot(self.description,'DAC_STATE')
        return self.description

    def identify(self):
        if self.config is None:self.load_configuration()
        status=self.raw_device.get_status()
        if status.get('protocol')!=2:raise ValueError('DAC API v2 driver required; update server package')
        configure_client_timeout(self.cli,120)
        if status.get('faulted'):self.raw_device.disconnect()
        return self._description(self.raw_device.connect(),adopt=True)

    def refresh(self):
        return self._description(self.raw_device.get_status())

    def _check_cancelled(self,handle):
        if handle:handle.check_cancelled()
        if self._closing:raise OperationCancelled('DAC client is closing')
        if time.monotonic()-self.ui_alive>=2.5:
            raise OperationCancelled('DAC UI heartbeat stopped; no next row sent')

    def _updates(self,state):
        return [[e.chip,e.channel,state.by_id[e.id]] for e in self.config.electrodes]

    def _apply(self,state,use_ldac,timing,reuse=False):
        status=self.raw_device.set_voltages(self._updates(state),self.configuration_id,
            use_ldac=use_ldac,command_gap_ms=timing.command_gap_ms,
            pre_ldac_ms=timing.pre_ldac_ms,cooldown_ms=timing.cooldown_ms,
            reuse_spi_config=reuse)
        self._description(status)
        return status

    def run_remote(self,action,payload):
        from labremote.data_paths import tab_data_directory
        handle=CURRENT_JOB.get()
        request_id=handle.request_id if handle else uuid4().hex
        payload=json.loads(json.dumps(payload,allow_nan=False))
        if self.config is None:self.load_configuration()
        if action=='connect':return self._description(self.raw_device.connect(),adopt=True)
        if action=='reload_config':
            self.load_configuration(payload.get('path'))
            return dict(result=self.refresh())
        folder=tab_data_directory(None,'dac',self.config.device)/'runs'/request_id
        atomic_json(folder/'request.json',dict(action=action,payload=payload,configuration=self.config.as_dict()))
        result=dict(job_id=request_id,action=action,status='running',row=0,total=1)
        try:
            self._check_cancelled(handle)
            if action=='initialize':
                values=payload.get('voltages')
                if values is None:values={e.id:0.0 for e in self.config.electrodes}
                state=VoltageSet.from_values(self.config,values)
                # Every physical output is initialized. Unmapped channels target 0 V.
                initial=[[0.0]*16 for _ in range(2)]
                for e in self.config.electrodes:initial[e.chip][e.channel]=state.by_id[e.id]
                status=self.raw_device.initialize([list(r) for r in self.config.offsets],initial,
                                                  use_ldac=payload.get('use_ldac',True))
                self._description(status,adopt=True)
                result['row']=1
            elif action in ('apply','step'):
                state=VoltageSet.from_values(self.config,payload['voltages'])
                if action=='step':state=step_set(state,payload['step'],payload['direction'],
                    electrode_id=payload.get('electrode_id'),component=payload.get('component'))
                timing=ManualTiming.from_dict(payload.get('manual_timing',{}))
                self._apply(state,payload.get('use_ldac',True),timing)
                result['row']=1
            elif action=='sequence':
                seq=VoltageSequence.from_dict(payload['sequence'],self.config)
                options=SequenceOptions.from_dict(payload.get('sequence_options',{}))
                result['total']=len(seq.rows)
                for index,row in enumerate(seq.rows,1):
                    self._check_cancelled(handle)
                    self._apply(row.state,seq.use_ldac,ManualTiming(0,options.pre_ldac_ms,0),options.reuse_spi_config)
                    applied=time.monotonic()
                    result.update(row=index,last_sent=dict(self.description['last_sent']))
                    self.task_progress.emit('DAC',dict(result))
                    atomic_json(folder/'rows'/f'{index:05d}.json',dict(result,voltages=row.state.by_id))
                    deadline=applied+row.hold_s
                    while time.monotonic()<deadline:
                        self._check_cancelled(handle)
                        time.sleep(min(.05,max(0,deadline-time.monotonic())))
            else:raise ValueError('Unknown DAC client action: '+action)
            result.update(status='completed',result=self.description)
            return result
        except OperationCancelled as exc:
            result.update(status='stopped',reason=str(exc),result=self.description)
            raise
        except Exception as exc:
            # Never replay a write after an ambiguous RPC error. Require reconnect.
            self.configuration_id=None
            if self.description:
                self.description=dict(self.description,ready=False,last_sent=None)
                self.publish_snapshot(self.description,'DAC_STATE')
            result.update(status='failed',error=str(exc))
            self.connection_error=True
            raise
        finally:
            self.task_progress.emit('DAC',dict(result))
            atomic_json(folder/'client_result.json',result)

    def disconnect_device(self):
        # Disconnect this client only; other clients may use the same server driver.
        self.configuration_id=None
        super().disconnect_device()

    def enqueue(self,handle):
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

    def reload_configuration(self,path=None):return self._job('reload_config',dict(path=str(path) if path else None))

    def cancel(self):self.worker.cancel_pending()

    def status(self):return self.refresh()
