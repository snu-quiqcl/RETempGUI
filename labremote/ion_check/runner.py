from labremote.devices.fpga.mapping import write_snapshot
from labremote.devices.fpga.mapping import bound_methods
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import hashlib
from labremote.api.devices import DeviceAPI
from labremote.runtime.workflow_runner import WorkflowTask,_TASK_LOCK
from labremote.runtime.errors import OperationCancelled
from labremote.data_paths import tab_data_directory
from . import config

@bound_methods('ion_check')
class IonCheckRunner(WorkflowTask):
    def __init__(self,worker):
        super().__init__(worker,'ION_CHECK');self.exclusive_fpga=True;self.result=None

    def start(self,*,settings=None,mode='workflow',directory=None,parent=None):
        from labremote.runtime.characterization_guard import join_completed
        join_completed((self.worker,))
        if mode not in ('once','workflow'):raise ValueError('Unknown Ion Check mode')
        c=config.validate(config.load() if settings is None else settings,require_thresholds=mode=='workflow')
        with _TASK_LOCK:
            return self.launch(self._execute,(self.worker,),dict(settings=c,mode=mode,
                directory=str(tab_data_directory(directory,'ion_check'))),parent)

    def _execute(self):
        from labremote.devices.fpga.adapter import Cancellation
        from .acquisition import run
        from labremote.devices.fpga.controller import hd
        c=self.settings['settings'];mode=self.settings['mode']
        folder=Path(self.settings['directory'])/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_ion_check_'+self.handle.request_id[:8])
        folder.mkdir(parents=True,exist_ok=False); write_snapshot(folder)
        source=folder/'source';source.mkdir()
        hashes={}
        for path in [*Path(__file__).parent.glob('*.py'),Path(hd.__file__)]:
            raw=path.read_bytes();(source/path.name).write_bytes(raw);hashes[path.name]=hashlib.sha256(raw).hexdigest()
        config.save(folder/'configuration.json',dict(settings=c,mode=mode,fpga=self.worker.name,
                    dac='not_implemented',cleanup_outputs=config.output_levels(c),source_sha256=hashes))
        samples=[];error=None;decision='unmeasured';cleanup_status='unknown'
        self.publish(phase='measuring',mode=mode,total=1 if mode=='once' else c['max_attempts'],settings=c,folder=str(folder),sample=None,result=None)
        def sample(value):
            samples.append(deepcopy(value));config.save(folder/'samples.json',samples)
            self.publish(phase='measuring',sample=value,completed=len(samples))
        def cleaned(value):
            nonlocal cleanup_status
            cleanup_status=value
        try:
            decision=self.call(DeviceAPI(self.worker,group=self.group)._submit('ION_CHECK_ACQUIRE',
                lambda w:run(w.raw_device.controller,c,mode,source/'sequence.py',Cancellation(),sample,cleaned)))
        except Exception as exc:error=exc
        if error is None and self.handle.cancelled():error=OperationCancelled('Ion Check cancelled')
        if samples:decision=samples[-1]['decision']
        status='cancelled' if isinstance(error,OperationCancelled) else 'failed' if error or (mode=='workflow' and decision!='normal') else 'completed'
        reason=str(error) if error else ('Ion check passed' if decision=='normal' else config.LABELS.get(decision,decision))
        report=dict(status=status,reason=reason,mode=mode,folder=str(folder),result_paths=[str(folder)],
                    continue_allowed=status=='completed' and decision=='normal' and cleanup_status=='completed',
                    cleanup_status=cleanup_status,metrics=dict(attempts_used=len(samples),decision=decision),
                    settings=c,samples=samples,measurement_status='failed' if error else 'completed',dac='not_implemented')
        config.save(folder/'result.json',report);self.result=report
        self.publish(phase=status,result=report)
        if error is not None:raise error
        return report
