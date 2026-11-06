"""Client-owned row execution and cancellable hold; no server sequence engine."""
import time
from labremote.devices.dac.sequence import VoltageSequence
from labremote.devices.dac.model import atomic_json
from .timing import ManualTiming, SequenceOptions


def run_sequence(worker,payload,handle,folder,result):
    seq=VoltageSequence.from_dict(payload['sequence'],worker.config)
    options=SequenceOptions.from_dict(payload.get('sequence_options',{}))
    result['total']=len(seq.rows)
    for index,row in enumerate(seq.rows,1):
        worker._check_cancelled(handle)
        worker._apply(row.state,seq.use_ldac,ManualTiming(0,options.pre_ldac_ms,0),options.reuse_spi_config)
        applied=time.monotonic()
        result.update(row=index,last_sent=dict(worker.description['last_sent']))
        worker.task_progress.emit('DAC',dict(result))
        atomic_json(folder/'rows'/f'{index:05d}.json',dict(result,voltages=row.state.by_id))
        deadline=applied+row.hold_s
        while time.monotonic()<deadline:
            worker._check_cancelled(handle)
            time.sleep(min(.05,max(0,deadline-time.monotonic())))
