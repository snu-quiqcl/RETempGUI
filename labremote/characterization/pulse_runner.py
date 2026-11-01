import csv
import hashlib
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from labremote.api.devices import DeviceAPI
from labremote.runtime.workflow_runner import WorkflowTask,_TASK_LOCK
from labremote.runtime.errors import OperationCancelled
from . import config,rabi,pulse_experiment as model

class PulseRunner(WorkflowTask):
    def __init__(self,worker,kind):
        super().__init__(worker,kind.upper());self.kind=kind;self.exclusive_fpga=True;self.results={}
    def start(self,chamber,*,settings=None,settings_file=None,directory=None,frequency_hz=None,parent=None):
        if self.handle is not None and self.handle.done.is_set():self.join()
        if settings is not None and settings_file is not None:raise ValueError('Choose settings or settings_file')
        c=model.load(self.kind,chamber,settings_file) if settings is None else model.validate(self.kind,settings)
        if c['chamber']!=chamber:raise ValueError('Experiment chamber mismatch')
        from labremote.runtime.characterization_guard import join_completed
        join_completed((self.worker,))
        request=dict(settings=c,frequency_hz=rabi.validate_frequency(frequency_hz),microwave_control='external',directory=str(Path(directory or Path(__file__).resolve().parents[2]/'data/characterization').expanduser().resolve()))
        with _TASK_LOCK:
            if self.worker.has_requests() or self.worker.waveform_runner.running() or any(t.running() for t in self.worker._background_tasks):raise RuntimeError('FPGA is busy')
            return self.launch(self._execute,(self.worker,),request,parent)
    def _execute(self):
        from labremote.operation.fpga.pulse_experiment import run
        from labremote.devices.fpga.adapter import Cancellation
        from labremote.devices.fpga.controller import hd
        c=self.settings['settings'];chamber=c['chamber'];kind=self.kind
        folder=Path(self.settings['directory'])/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+kind+'_'+chamber+'_'+self.handle.request_id);folder.mkdir(parents=True,exist_ok=False)
        names=['pulse_experiment.py',kind+'_sequence.py']+(['ramsey_fit.py'] if kind=='ramsey' else ['initialization_analysis.py'] if kind=='initialization' else [])
        config.save(folder/'configuration.json',dict(**self.settings,run_id=self.handle.request_id,fpga=self.worker.name,hardware_definition=hd.__name__,clock_ns=10,source_sha256={n:hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest() for n in names}))
        from .live_pulse import LiveSummary
        live=LiveSummary(kind,c)
        records={};error=None;total=c['N_init_control'] if kind=='initialization' else c['max_precession_count'] if kind=='ramsey' else 2*c['N_repeat']
        self.publish(chamber=chamber,phase='Starting',folder=str(folder),points=0,total=total)
        try:
            with (folder/'raw_fifo.csv').open('w',newline='',encoding='utf-8') as stream:
                writer=csv.writer(stream);writer.writerow(['batch','condition','fifo_0','fifo_1','photon_count','tag','valid'])
                def rows(batch,condition,values,valid):writer.writerows([[batch,condition,*r,int(valid)] for r in values]);stream.flush()
                def record(value):
                    records[value['index']]=deepcopy(value)
                    snapshot=live.add(value)
                    self.publish(**({'live':snapshot} if snapshot is not None else {}),phase='Measuring',points=sum(r['complete'] for r in records.values()),received_samples=sum(len(r['counts']) for r in records.values()))
                self.call(DeviceAPI(self.worker,group=self.group)._submit(self.label+'_ACQUIRE',lambda w:run(w.raw_device.controller,kind,c,Cancellation(),rows,record)))
        except Exception as exc:error=exc
        values=[records[i] for i in sorted(records)]
        report=dict(experiment=kind,chamber=chamber,run_id=self.handle.request_id,folder=str(folder),microwave_control='external',frequency_hz=self.settings['frequency_hz'],completed_points=sum(r['complete'] for r in values),expected_points=total,error=str(error) if error else '')
        data=None
        try:
            config.save(folder/'points.json',values);self.publish(phase='Analyzing / saving')
            data=model.analyze(kind,values,c);config.save(folder/'analysis.json',data)
            with (folder/'summary.csv').open('w',newline='',encoding='utf-8') as stream:
                writer=csv.writer(stream)
                if kind in ('ramsey','initialization'):
                    writer.writerow(['time_s','received_shots','bright_shots','population','population_error']);writer.writerows(zip(data['time_s'],data['shot_counts'],data['bright_counts'],data['population'],data['population_error']))
                else:
                    columns=['condition','N_attempts','N_success','N_received','N_error','success_probability','spam_error','conditional_fidelity'];writer.writerow(columns);writer.writerows([[s[k] for k in columns] for s in data['states']])
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            figure=Figure(figsize=(9,10));FigureCanvasAgg(figure);model.draw(figure,data);figure.savefig(folder/'analysis.png',dpi=130)
        except Exception as exc:error=error or exc;report['analysis_error']=str(exc)
        if self.handle.cancelled() and error is None:error=OperationCancelled(kind+' cancelled')
        report.update(status='cancelled' if isinstance(error,OperationCancelled) else 'failed' if error else 'completed',error=str(error) if error else '')
        config.save(folder/'result.json',report);self.results[chamber]={'report':report,'data':data};self.publish(phase=report['status'],analysis=data,result=report)
        if error is not None:raise error
        return report
