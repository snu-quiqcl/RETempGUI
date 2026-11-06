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
    folder=tab_data_directory(None,'dac',worker.config.device)/'runs'/request_id
    atomic_json(folder/'request.json',dict(action=action,payload=payload,configuration=worker.config.as_dict()))
    result=dict(job_id=request_id,action=action,status='running',row=0,total=1)
    try:
        worker._check_cancelled(handle)
        if action=='initialize':
            initialize(worker,payload)
            result['row']=1
        elif action in ('apply','step'):
            state=VoltageSet.from_values(worker.config,payload['voltages'])
            if action=='step':state=step_set(state,payload['step'],payload['direction'],
                electrode_id=payload.get('electrode_id'),component=payload.get('component'))
            timing=ManualTiming.from_dict(payload.get('manual_timing',{}))
            worker._apply(state,payload.get('use_ldac',True),timing)
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
        # Never replay a write after an ambiguous RPC error. Require reconnect.
        worker.configuration_id=None
        if worker.description:
            worker.description=dict(worker.description,ready=False,last_sent=None)
            worker.publish_snapshot(worker.description,'DAC_STATE')
        result.update(status='failed',error=str(exc))
        worker.connection_error=True
        raise
    finally:
        worker.task_progress.emit('DAC',dict(result))
        atomic_json(folder/'client_result.json',result)

