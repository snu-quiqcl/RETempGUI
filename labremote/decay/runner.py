import csv
import hashlib
from pathlib import Path
from datetime import datetime
from labremote.runtime.workflow_runner import WorkflowTask,_TASK_LOCK
from labremote.runtime.errors import OperationCancelled
from labremote.api.devices import DeviceAPI
from . import config
from .plotting import Accumulator,DecayPlot

class DecayRunner(WorkflowTask):
    def __init__(self,worker):
        super().__init__(worker,'DECAY');self.exclusive_fpga=True;self.results={}
    def start(self,chamber,mode,*,settings=None,settings_file=None,directory=None,parent=None):
        from labremote.runtime.characterization_guard import join_completed
        join_completed((self.worker,))
        if settings is not None and settings_file is not None:raise ValueError('Choose settings or settings_file')
        c=config.load(chamber,mode,settings_file) if settings is None else config.validate(settings)
        if (c['chamber'],c['mode'])!=(chamber,mode):raise ValueError('Decay chamber/mode mismatch')
        with _TASK_LOCK:
            if self.worker.has_requests() or self.worker.waveform_runner.running() or any(t.running() for t in self.worker._background_tasks):raise RuntimeError('FPGA busy')
            return self.launch(self._execute,(self.worker,),dict(settings=c,directory=str(Path(directory or Path(__file__).resolve().parents[2]/'data/decay').resolve())),parent)
    def _execute(self):
        from labremote.devices.fpga.adapter import Cancellation
        from labremote.devices.fpga.controller import hd
        from labremote.operation.fpga.decay import run
        c=self.settings['settings'];folder=Path(self.settings['directory'])/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_Decay_'+c['chamber']+'_'+c['mode']+'_'+self.handle.request_id)
        folder.mkdir(parents=True,exist_ok=False)
        sources={n:hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest() for n in ('config.py','sequence.py','runner.py','plotting.py')}
        import shutil
        source_root=folder/'source';source_root.mkdir()
        for name in sources:shutil.copyfile(Path(__file__).parent/name,source_root/name)
        operation=Path(__file__).resolve().parents[1]/'operation/fpga/decay.py'
        for name,path in [('operation.py',operation),('hardware_definition.py',Path(hd.__file__)),('HardwareDefinition_v4_04.py',Path(hd.__file__).with_name('HardwareDefinition_v4_04.py'))]:
            shutil.copyfile(path,source_root/name);sources[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        config.save(folder/'configuration.json',dict(settings=c,run_id=self.handle.request_id,fpga=self.worker.name,hardware_definition=hd.__name__,sequencer_clock_ns=10,stopwatch_bin_ns=1.25,source_sha256=sources,
            acquisition_note='16-bit histogram protected by chunks <=65535 pulse trials; host pauses between chunks; SYNC arrival required'))
        acc=Accumulator(c);error=None
        self.publish(chamber=c['chamber'],mode=c['mode'],phase='Starting',folder=str(folder),total=c['outer_loop'])
        try:
            with (folder/'raw_fifo.csv').open('w',newline='',encoding='utf-8') as raw,(folder/'chunks.jsonl').open('w',encoding='utf-8') as chunks:
                import json
                writer=csv.writer(raw);writer.writerow(['batch','chunk','fifo_0','fifo_1','fifo_2','tag','valid'])
                def rows(batch,chunk,values,valid):
                    if isinstance(values,list):
                        for r in values:writer.writerow([batch,chunk,*(r if isinstance(r,(list,tuple)) else [repr(r)]),int(valid)])
                    else:writer.writerow([batch,chunk,repr(values),0])
                    raw.flush()
                def received(chunk):
                    chunks.write(json.dumps(chunk,allow_nan=False)+'\n');chunks.flush();acc.add(chunk)
                    self.publish(phase='Measuring',live=acc.data(),completed_batches=sum(b['complete'] for b in acc.batches.values()))
                self.call(DeviceAPI(self.worker,group=self.group)._submit('DECAY_ACQUIRE',lambda w:run(w.raw_device.controller,c,Cancellation(),rows,received)))
        except Exception as exc:error=exc
        data=acc.data();report=dict(experiment='decay',chamber=c['chamber'],mode=c['mode'],run_id=self.handle.request_id,folder=str(folder),completed_batches=sum(b['complete'] for b in data['batches']),expected_batches=c['outer_loop'])
        try:
            config.save(folder/'histogram.json',data)
            with (folder/'histogram.csv').open('w',newline='',encoding='utf-8') as stream:
                writer=csv.writer(stream);writer.writerow(['bin','time_ns']+[c['roles']['PMT'+str(i+1)] for i in range(acc.channels)])
                for i in range(c['MAX_TIME_DIFFERENCE']):writer.writerow([i,i*1.25]+[channel[i] for channel in data['counts']])
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            fig=Figure(figsize=(11,8));FigureCanvasAgg(fig);plot=DecayPlot(fig,c);plot.update(data);fig.savefig(folder/'decay.png',dpi=130)
        except Exception as exc:error=error or exc
        if self.handle.cancelled() and error is None:error=OperationCancelled('Decay cancelled')
        report.update(status='cancelled' if isinstance(error,OperationCancelled) else 'failed' if error else 'completed',error=str(error) if error else '')
        config.save(folder/'result.json',report);self.results[c['chamber'],c['mode']]=dict(report=report,data=data,settings=c)
        self.publish(phase=report['status'],result=report,live=data)
        if error:raise error
        return report
