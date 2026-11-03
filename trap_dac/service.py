"""Server-owned USB, bounded asynchronous jobs and per-executor heartbeat leases.

No Qt/QCoDeS dependency. All hardware I/O runs on one job thread per DAC.
Status/heartbeat never read DAC registers or wait for serial I/O.
"""
import copy
import hashlib
import json
import threading
import time
import os
import re
from pathlib import Path
from uuid import uuid4
from .configuration import load_config, DeviceConfig
from .hardware import DACSession, open_transport
from .model import VoltageSet, step_set, atomic_json
from .sequence import VoltageSequence, execute_recorded_sequence
from .timing import ManualTiming, SequenceOptions

_PORT_LOCK=threading.Lock()
_PORT_OWNERS={}


def fingerprint(config):
    doc=config.as_dict();doc.pop('default_port',None)
    return hashlib.sha256(json.dumps(doc,sort_keys=True).encode()).hexdigest()


class DACService:
    def __init__(self, config_path, serial_port, data_root, *, lease_seconds=5.0,
                 internal_reference=False, transport_factory=None):
        self.config_path=Path(config_path).resolve()
        self.config=load_config(self.config_path)
        self.serial_port=str(serial_port)
        if not self.serial_port.strip():raise ValueError('Explicit server USB serial_port required')
        self.data_root=Path(data_root).resolve()/self.config.device
        if not 2<=float(lease_seconds)<=300:raise ValueError('lease_seconds must be 2..300')
        if type(internal_reference) is not bool:raise ValueError('internal_reference must be boolean')
        self.lease_seconds=float(lease_seconds);self.internal_reference=internal_reference
        self.factory=transport_factory or (lambda port:open_transport(port,False))
        self.port_key=os.path.normcase(os.path.realpath(self.serial_port))
        self.session=None;self.last_sent=None;self.last_ldac=None
        self._lock=threading.RLock();self._active=None;self._jobs={};self._closed=False
        self._exit=threading.Event()
        self._watcher=threading.Thread(target=self._watch,name='DAC lease '+self.config.device,daemon=True)
        self._watcher.start()

    def describe(self):
        with self._lock:
            return dict(protocol=1,device=self.config.device,configuration=self.config.as_dict(),
                        fingerprint=fingerprint(self.config),lease_seconds=self.lease_seconds,
                        connected=self.session is not None,ready=bool(self.session and self.session.ready),
                        last_sent=copy.deepcopy(self.last_sent),last_ldac=self.last_ldac,
                        last_transfer=copy.deepcopy(self.session.last_transfer) if self.session else {},
                        readback_verified=False,active_job=self._active)

    def status(self, job_id):
        with self._lock:
            job=self._jobs[job_id]
            return copy.deepcopy({k:v for k,v in job.items() if k not in ('event','thread','owner','deadline','request_hash')})

    def heartbeat(self, owner, job_id):
        with self._lock:
            job=self._jobs[job_id]
            if job['owner']!=owner:raise PermissionError('Job belongs to another UI session')
            if job['status']=='running' and not job['event'].is_set():
                job['deadline']=time.monotonic()+self.lease_seconds
            return self.status(job_id)

    def stop(self, owner, job_id, reason='user_stop'):
        with self._lock:
            job=self._jobs[job_id]
            if job['owner']!=owner:raise PermissionError('Job belongs to another UI session')
            if job['status']=='running':
                job['reason']=job['reason'] or str(reason);job['event'].set()
            return self.status(job_id)

    def _watch(self):
        while not self._exit.wait(.1):
            with self._lock:
                if self._active:
                    job=self._jobs[self._active]
                    if time.monotonic()>job['deadline'] and not job['event'].is_set():
                        job['reason']='ui_connection_lost';job['event'].set()

    def start(self, owner, request_id, action, payload):
        if not isinstance(owner,str) or not re.fullmatch('[0-9a-f]{32}',owner):raise ValueError('Invalid session ID')
        if not isinstance(request_id,str) or not re.fullmatch('[0-9a-f]{32}',request_id):raise ValueError('Invalid request ID')
        if action not in ('connect','disconnect','initialize','apply','step','sequence','reload_config'):
            raise ValueError('Unsupported DAC action')
        payload=json.loads(json.dumps(payload,allow_nan=False))
        request_hash=hashlib.sha256(json.dumps([action,payload],sort_keys=True).encode()).hexdigest()
        with self._lock:
            if self._closed:raise RuntimeError('Service closed')
            if request_id in self._jobs:
                old=self._jobs[request_id]
                if old['owner']!=owner or old['request_hash']!=request_hash:raise ValueError('Request ID reused with different content')
                return self.status(request_id)
            if self._active:raise RuntimeError('DAC busy: manual/sequence requests are not queued')
            if (self.data_root/'runs'/request_id).exists():raise RuntimeError('Request ID already archived; do not replay after server restart')
            if action not in ('connect','reload_config') and self.session is None:raise RuntimeError('Connect DAC first')
            if action in ('initialize','apply','step','sequence'):
                if payload.get('fingerprint')!=fingerprint(self.config):raise ValueError('Server mapping/calibration changed; reload configuration')
            # Validate complete requests BEFORE scheduling any hardware writes.
            parsed=None
            if action=='initialize':
                values=payload.get('voltages')
                parsed=VoltageSet.from_values(self.config,values if values is not None else {e.id:0.0 for e in self.config.electrodes})
            elif action in ('apply','step'):
                parsed=VoltageSet.from_values(self.config,payload.get('voltages'),name=payload.get('name','Manual'),notes=payload.get('notes',''))
                if action=='step':parsed=step_set(parsed,payload['step'],payload['direction'],electrode_id=payload.get('electrode_id'),component=payload.get('component'))
                ManualTiming.from_dict(payload.get('manual_timing',{}))
            elif action=='sequence':
                parsed=VoltageSequence.from_dict(payload['sequence'],self.config)
                SequenceOptions.from_dict(payload.get('sequence_options',{}))
            if action in ('initialize','apply','step') and type(payload.get('use_ldac',True)) is not bool:raise ValueError('use_ldac must be boolean')
            if action in ('apply','step','sequence') and not self.session.ready:raise RuntimeError('Initialize DAC first')
            if action=='reload_config':parsed=load_config(self.config_path,self.config.device)
            job=dict(job_id=request_id,owner=owner,action=action,status='running',reason='',error='',row=0,total=len(parsed.rows) if action=='sequence' else 1,
                     started_at=time.time(),deadline=time.monotonic()+self.lease_seconds,event=threading.Event(),request_hash=request_hash,result=None)
            self._jobs[request_id]=job;self._active=request_id
            thread=threading.Thread(target=self._execute,args=(job,payload,parsed),name='DAC '+action,daemon=True)
            job['thread']=thread;thread.start()
            return self.status(request_id)

    def _execute(self, job, payload, parsed):
        action=job['action'];event=job['event'];result=None;error='';status='completed'
        folder=self.data_root/'runs'/job['job_id']
        try:
            atomic_json(folder/'request.json',dict(action=action,payload=payload,configuration=self.config.as_dict(),readback_verified=False))
            if event.is_set():raise InterruptedError('Stopped before execution')
            if action=='connect':
                if self.session is None:
                    with _PORT_LOCK:
                        if self.port_key in _PORT_OWNERS:raise RuntimeError('USB port already owned by another DAC')
                        _PORT_OWNERS[self.port_key]=self
                    try:self.session=DACSession(self.config,self.factory(self.serial_port))
                    except Exception:
                        self._release_port();raise
            elif action=='disconnect':
                self.session.close();self.session=None;self._release_port();self.last_sent=None;self.last_ldac=None
            elif action=='reload_config':
                if self.session:self.session.close();self.session=None;self._release_port()
                self.config=parsed;self.last_sent=None;self.last_ldac=None
            elif action=='initialize':
                self.session.initialize(parsed.by_id,use_ldac=payload.get('use_ldac',True),
                    internal_reference=self.internal_reference,stop_event=event)
                self._sent(parsed,payload.get('use_ldac',True),job,1)
            elif action in ('apply','step'):
                self.session.apply(parsed,use_ldac=payload.get('use_ldac',True),profile='manual',
                    manual_timing=ManualTiming.from_dict(payload.get('manual_timing',{})))
                self._sent(parsed,payload.get('use_ldac',True),job,1)
                atomic_json(folder/'sent.json',parsed.as_dict(readback_verified=False,transfer=self.session.last_transfer))
            elif action=='sequence':
                outcome=execute_recorded_sequence(self.session,parsed,event,folder,self.serial_port,
                    on_applied=lambda index,state,elapsed:self._sent(state,parsed.use_ldac,job,index),
                    options=SequenceOptions.from_dict(payload.get('sequence_options',{})))
                status=outcome.status;error=outcome.error or ''
                if not self.session.ready:self.last_sent=None;self.last_ldac=None
            result=self.describe()
            if event.is_set() and status=='completed':status='stopped'
        except InterruptedError as exc:status='stopped';error=str(exc)
        except Exception as exc:
            status='failed';error=f'{type(exc).__name__}: {exc}'
            if self.session is not None and not self.session.ready:
                self.last_sent=None;self.last_ldac=None
        if result is None:result=self.describe()
        # Publish final state only AFTER the durable result has been written.
        final=dict(job_id=job['job_id'],action=action,status=status,error=error,reason=job['reason'],
                   row=job['row'],total=job['total'],result=result,readback_verified=False)
        try:atomic_json(folder/'result.json',final)
        except Exception as exc:status='failed';error+=(('; ' if error else '')+'Result save failed: '+str(exc))
        with self._lock:
            if isinstance(result,dict):result['active_job']=None
            job.update(status=status,error=error,result=result,finished_at=time.time(),archive=str(folder))
            self._active=None

    def _release_port(self):
        with _PORT_LOCK:
            if _PORT_OWNERS.get(self.port_key) is self:_PORT_OWNERS.pop(self.port_key)

    def _sent(self, state, ldac, job, row):
        with self._lock:
            self.last_sent=dict(state.by_id);self.last_ldac=ldac
            job['row']=row
            job['last_sent']=dict(state.by_id)

    def close(self):
        with self._lock:
            self._closed=True
            job=self._jobs.get(self._active)
            if job:job['reason']='server_shutdown';job['event'].set()
        if job:job['thread'].join()  # Bounded serial writes; finish current row.
        self._exit.set();self._watcher.join(1)
        if self.session:self.session.close();self.session=None
        self._release_port()
