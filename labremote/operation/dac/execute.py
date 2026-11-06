"""Execute and record one client DAC operation; never implements a server job."""
import json
from uuid import uuid4
from labremote.runtime.jobs import CURRENT_JOB
from labremote.runtime.errors import OperationCancelled
from labremote.devices.dac.model import atomic_json, VoltageSet, step_set
from .timing import ManualTiming
from .initialize import initialize
from .run_sequence import run_sequence

def execute(worker,action,payload):
    from labremote.data_paths import tab_data_directory
    handle=CURRENT_JOB.get()
    request_id=handle.request_id if handle else uuid4().hex
    payload=json.loads(json.dumps(payload,allow_nan=False))
    if worker.config is None:worker.load_configuration()
    if action=='connect':return worker._description(worker.raw_device.connect(),adopt=True)
    if action=='reload_config':
        worker.load_configuration(payload.get('path'))
        return dict(result=worker.refresh())
    if action=='recover':return dict(result=worker._description(worker.raw_device.recover(),adopt=True))
    folder=tab_data_directory(None,'dac',worker.config.device)/'runs'/request_id
    atomic_json(folder/'request.json',dict(action=action,payload=payload,configuration=worker.config.as_dict()))
    result=dict(job_id=request_id,action=action,status='running',row=0,total=1)
    try:
        worker._check_cancelled(handle)
        if action=='initialize':
            initialize(worker,payload)
            result['row']=1
        elif action in ('apply','step','set_channel'):
            from .set_voltages import set_voltages
            current=worker.synchronize()
            selected=None;revision=None
            if action=='apply':
                state=VoltageSet.from_values(worker.config,payload['voltages'])
            else:
                base=VoltageSet.from_values(worker.config,current['last_sent'])
                if action=='step':
                    state=step_set(base,payload['step'],payload['direction'],
                        electrode_id=payload.get('electrode_id'),component=payload.get('component'))
                    selected=[eid for eid,v in state.by_id.items() if v!=base.by_id[eid]]
                else:
                    eid=payload['electrode']
                    if eid not in base.by_id:raise ValueError('Unknown electrode')
                    state=VoltageSet.from_values(worker.config,{**base.by_id,eid:payload['voltage']})
                    selected=[eid]
                revision=current.get('state_revision')
            timing=ManualTiming.from_dict(payload.get('manual_timing',{}))
            set_voltages(worker,state,payload.get('use_ldac',True),timing,
                         electrode_ids=selected,expected_revision=revision)
            result['row']=1
        elif action=='sequence':
            run_sequence(worker,payload,handle,folder,result)
        else:raise ValueError('Unknown DAC client action: '+action)
        result.update(status='completed',result=worker.description)
        return result
    except OperationCancelled as exc:
        result.update(status='stopped',reason=str(exc),result=worker.description)
        raise
    except Exception as exc:
        # A rejected write is not a broken connection. Never replay a write.
        worker.configuration_id=None
        if worker.description:
            worker.description=dict(worker.description,ready=False,last_sent=None)
            worker.publish_snapshot(worker.description,'DAC_STATE')
        transport_error=isinstance(exc,(ConnectionError,TimeoutError)) or 'Server did not reply before timeout' in str(exc)
        if not transport_error:
            try:worker.refresh()
            except Exception:pass
        result.update(status='failed',error=str(exc),result=worker.description)
        raise
    finally:
        worker.task_progress.emit('DAC',dict(result))
        atomic_json(folder/'client_result.json',result)

