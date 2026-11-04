import csv
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from labremote.data_paths import tab_data_directory
from labremote.runtime.workflow_runner import WorkflowTask, _TASK_LOCK
from labremote.runtime.errors import OperationCancelled
from labremote.api.devices import DeviceAPI
from . import config
from .plotting import Accumulator, HOMPlot


class HOMRunner(WorkflowTask):
    def __init__(self,worker):
        super().__init__(worker,'HOM'); self.exclusive_fpga=True; self.result=None

    def start(self,*,settings=None,settings_file=None,directory=None,parent=None):
        from labremote.runtime.characterization_guard import join_completed
        join_completed((self.worker,))
        if settings is not None and settings_file is not None:raise ValueError('Choose settings or settings_file')
        c=config.load(settings_file) if settings is None else config.validate(settings)
        with _TASK_LOCK:
            if self.worker.has_requests() or self.worker.waveform_runner.running() or any(t.running() for t in self.worker._background_tasks):raise RuntimeError('FPGA busy')
            return self.launch(self._execute,(self.worker,),dict(settings=c,directory=str(tab_data_directory(directory,'hom'))),parent)

    def _execute(self):
        from labremote.devices.fpga.adapter import Cancellation
        from .acquisition import run
        c=self.settings['settings']; folder=Path(self.settings['directory'])/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_HOM_'+self.handle.request_id[:8])
        folder.mkdir(parents=True,exist_ok=False); source=folder/'source'; source.mkdir()
        files={p.name:p for p in Path(__file__).parent.glob('*.py')}
        files['hardware_definition.py']=Path(config.hd.__file__)
        files['HardwareDefinition_v4_04.py']=Path(config.hd.__file__).with_name('HardwareDefinition_v4_04.py')
        files['SequencerProgram_v1_08.py']=Path(config.hd.__file__).with_name('SequencerProgram_v1_08.py')
        files['SequencerUtility_v1_03.py']=Path(config.hd.__file__).with_name('SequencerUtility_v1_03.py')
        hashes={}
        for name,path in files.items():shutil.copyfile(path,source/name); hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        config.save(folder/'configuration.json',dict(settings=c,run_id=self.handle.request_id,fpga=self.worker.name,source_sha256=hashes,sequencer_clock_ns=10,stopwatch_bin_ns=1.25,
            normalization='Counts / valid SYNC trials. Reference: equal contributions, 50:50 splitter, weak-detection approximation; per-batch cross-correlation / (2 N^2), trial-weighted across batches. Total decay is mean detected counts/trial, not an at-least-one-event probability.'))
        acc=Accumulator(c); error=None; cleanup_status='unknown'
        def cleaned(status):
            nonlocal cleanup_status
            cleanup_status=status
        self.publish(phase='Starting',folder=str(folder),total=c['outer_loop']*c['outer_outer_loop'],live=acc.data())
        try:
            with (folder/'raw_fifo.csv').open('w',newline='',encoding='utf-8') as raw,(folder/'batches.jsonl').open('w',encoding='utf-8') as batches:
                writer=csv.writer(raw); writer.writerow(['batch','word0','word1','word2','tag','structurally_valid'])
                def rows(batch,values,valid):
                    for row in values if isinstance(values,list) else [values]:writer.writerow([batch,*(row if isinstance(row,(tuple,list)) else [repr(row)]),int(valid)])
                    raw.flush()
                def received(b):
                    batches.write(json.dumps(b,allow_nan=False)+'\n'); batches.flush(); acc.add(b)
                    self.publish(phase='Measuring',live=acc.data(),completed_batches=len(acc.batches))
                self.call(DeviceAPI(self.worker,group=self.group)._submit('HOM_ACQUIRE',lambda w:run(w.raw_device.controller,c,Cancellation(),rows,received,cleaned)))
        except Exception as exc:
            error=exc
        data=acc.data()
        try:
            config.save(folder/'histogram.json',data)
            with (folder/'histogram.csv').open('w',newline='',encoding='utf-8') as stream:
                writer=csv.writer(stream); writer.writerow(['index','delay_ns','hom_count','hom_probability','reference_probability','pmta_time_ns','pmta_count','pmtc_count'])
                m=c['MAX_TIME_DIFFERENCE']; n=data['trials']
                for i in range(2*m):writer.writerow([i,(i-m)*1.25,data['hom'][i],data['hom'][i]/n if n else '',data['reference_probability'][i],i*1.25 if i<m else '',data['a'][i] if i<m else '',data['c'][i] if i<m else ''])
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            fig=Figure(figsize=(14,11)); FigureCanvasAgg(fig); HOMPlot(fig,c).update(data); fig.savefig(folder/'hom.png',dpi=150)
        except Exception as exc:error=error or exc
        if self.handle.cancelled() and error is None:error=OperationCancelled('HOM cancelled')
        report=dict(experiment='hom',status='cancelled' if isinstance(error,OperationCancelled) else 'failed' if error else 'completed',error=str(error) if error else '',
            folder=str(folder),run_id=self.handle.request_id,completed_batches=len(acc.batches),expected_batches=c['outer_loop']*c['outer_outer_loop'],metrics=data['metrics'],cleanup_status=cleanup_status,
            continue_allowed=cleanup_status=='completed' and not isinstance(error,(ConnectionError,TimeoutError)))
        config.save(folder/'result.json',report); self.result=dict(report=report,data=data,settings=c)
        self.publish(phase=report['status'],result=report,live=data)
        if error:raise error
        return report
