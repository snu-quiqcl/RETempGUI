"""Upload calibration and initialize all physical DAC outputs."""
from labremote.devices.dac.model import VoltageSet


def initialize(worker,payload):
    values=payload.get('voltages')
    if values is None:values={e.id:0.0 for e in worker.config.electrodes}
    state=VoltageSet.from_values(worker.config,values)
    initial=[[0.0]*16 for _ in range(2)]
    for e in worker.config.electrodes:initial[e.chip][e.channel]=state.by_id[e.id]
    status=worker.raw_device.initialize([list(r) for r in worker.config.offsets],initial,
                                       use_ldac=payload.get('use_ldac',True))
    description=worker._description(status,adopt=True)
    if not description['ready']:
        raise ValueError('Initialization returned incompatible state: '+description['status_reason'])
    return description
