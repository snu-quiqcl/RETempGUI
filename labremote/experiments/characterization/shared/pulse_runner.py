from labremote.runtime.queue_archive import active as queue_archive_active
from labremote.runtime.storage_paths import compact_run_folder
from labremote.devices.fpga.mapping import write_snapshot
from labremote.devices.fpga.mapping import bound_methods
import csv
import hashlib
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from labremote.data_paths import characterization_directory
from labremote.api.devices import DeviceAPI
from labremote.runtime.workflow_runner import WorkflowTask, _TASK_LOCK
from labremote.runtime.errors import OperationCancelled
from labremote.experiments.characterization.shared import config, pulse_model as model; from labremote.experiments.characterization.rabi import model as rabi

@bound_methods('pulse')
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
        request=dict(settings=c,frequency_hz=rabi.validate_frequency(frequency_hz),microwave_control='external',directory=str(characterization_directory(directory, chamber, self.kind)))
        with _TASK_LOCK:
            return self.launch(self._execute,(self.worker,),request,parent)
    def _execute(self):
        from labremote.experiments.characterization.shared.pulse_acquisition import run
        from labremote.devices.fpga.adapter import Cancellation
        from labremote.devices.fpga.controller import hd
        c=self.settings['settings'];chamber=c['chamber'];kind=self.kind
        folder=Path(self.settings['directory'])/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+kind+'_'+chamber+'_'+self.handle.request_id);folder=compact_run_folder(folder); folder.mkdir(parents=True,exist_ok=queue_archive_active()); write_snapshot(folder)
        names=['pulse_experiment.py',kind+'_sequence.py']+(['spin_echo_analysis.py','ramsey_sequence.py'] if kind=='spin_echo' else ['ramsey_fit.py'] if kind=='ramsey' else ['initialization_analysis.py'] if kind=='initialization' else [])
        if kind=='spam':names.append('detector_comparison.py')
        source_root=Path(__file__).resolve().parents[1]
        source_paths={'detector_comparison.py':source_root.parent/'detector_comparison.py','pulse_experiment.py':Path(model.__file__),kind+'_sequence.py':source_root/kind/'sequence.py',
                      'spin_echo_analysis.py':source_root/'spin_echo/analysis.py','ramsey_sequence.py':source_root/'ramsey/sequence.py',
                      'ramsey_fit.py':source_root/'ramsey/analysis.py','initialization_analysis.py':source_root/'initialization/analysis.py'}
        config.save(folder/'configuration.json',dict(**self.settings,run_id=self.handle.request_id,fpga=self.worker.name,hardware_definition=hd.__name__,clock_ns=10,source_sha256={n:hashlib.sha256(source_paths[n].read_bytes()).hexdigest() for n in names}))
        from labremote.experiments.characterization.shared.live_pulse import LiveSummary
        if kind=='spam':
            from labremote.experiments.characterization.spam.live import LiveSummary as SpamSummary
            live=SpamSummary(c)
        else:live=LiveSummary(kind,c)
        records={};error=None;total=c['N_init_control'] if kind=='initialization' else c['max_precession_count'] if kind in ('ramsey','spin_echo') else 2*c['N_repeat']
        self.publish(chamber=chamber,phase='Starting',folder=str(folder),points=0,total=total)
        try:
            with (folder/'raw_fifo.csv').open('w',newline='',encoding='utf-8') as stream:
                writer=csv.writer(stream);writer.writerow(['batch','condition','shot','count_pmt1','count_pmt2','tag','valid'] if c.get('detector_count',1)==2 else ['batch','condition','fifo_0','fifo_1','photon_count','tag','valid'])
                def rows(batch,condition,values,valid):writer.writerows([[batch,condition,*r,int(valid)] for r in values]);stream.flush()
                def record(value):
                    records[value['index']]=deepcopy(value)
                    snapshot=live.add(value)
                    self.publish(**({'live':snapshot} if snapshot is not None else {}),phase='Measuring',points=sum(r['complete'] for r in records.values()),received_samples=sum(len(rabi.counts_by_detector(r['counts'])['PMT']) for r in records.values()))
                self.call(DeviceAPI(self.worker,group=self.group)._submit(self.label+'_ACQUIRE',lambda w:run(w.raw_device.controller,kind,c,Cancellation(),rows,record)))
        except Exception as exc:error=exc
        values=[records[i] for i in sorted(records)]
        report=dict(experiment=kind,chamber=chamber,run_id=self.handle.request_id,folder=str(folder),microwave_control='external',frequency_hz=self.settings['frequency_hz'],completed_points=sum(r['complete'] for r in values),expected_points=total,error=str(error) if error else '')
        if kind=='spam':report['detector_count']=c.get('detector_count',1)
        data=None
        try:
            config.save(folder/'points.json',values);self.publish(phase='Analyzing / saving')
            data=model.analyze(kind,values,c);config.save(folder/'analysis.json',data)
            with (folder/'summary.csv').open('w',newline='',encoding='utf-8') as stream:
                writer=csv.writer(stream)
                if kind in ('ramsey','spin_echo','initialization'):
                    writer.writerow(['time_s','received_shots','bright_shots','population','population_error']);writer.writerows(zip(data['time_s'],data['shot_counts'],data['bright_counts'],data['population'],data['population_error']))
                else:
                    columns=['condition','N_attempts','N_success','N_received','N_error','success_probability','spam_error','conditional_fidelity']
                    dual=c.get('detector_count',1)==2;writer.writerow((['detector'] if dual else [])+columns)
                    for role,channel in model.detector_data(data).items():
                        writer.writerows([([role] if dual else [])+[state[k] for k in columns] for state in channel['states']])
            if not queue_archive_active():
                from matplotlib.figure import Figure
                from matplotlib.backends.backend_agg import FigureCanvasAgg
                figure=Figure(figsize=(9,10));FigureCanvasAgg(figure);model.draw(figure,data);figure.savefig(folder/'analysis.png',dpi=130)
        except Exception as exc:error=error or exc;report['analysis_error']=str(exc)
        if self.handle.cancelled() and error is None:error=OperationCancelled(kind+' cancelled')
        report.update(status='cancelled' if isinstance(error,OperationCancelled) else 'failed' if error else 'completed',error=str(error) if error else '')
        config.save(folder/'result.json',report);self.results[chamber]={'report':report,'data':data};self.publish(phase=report['status'],analysis=data,result=report)
        if error is not None:raise error
        return report
