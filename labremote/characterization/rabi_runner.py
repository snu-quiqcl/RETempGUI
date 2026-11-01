import csv
import hashlib
from datetime import datetime
from pathlib import Path
from labremote.api.devices import DeviceAPI
from labremote.runtime.workflow_runner import WorkflowTask,_TASK_LOCK
from labremote.runtime.errors import OperationCancelled
from . import config,rabi

class RabiRunner(WorkflowTask):
    def __init__(self,worker):
        super().__init__(worker,'RABI');self.exclusive_fpga=True;self.results={}

    def start(self,chamber,*,settings=None,settings_file=None,directory=None,frequency_hz=None,parent=None):
        if self.handle is not None and self.handle.done.is_set():self.join()
        if settings is not None and settings_file is not None:raise ValueError('Choose settings or settings_file')
        c=rabi.load(chamber,settings_file) if settings is None else rabi.validate(settings)
        if c['chamber']!=chamber:raise ValueError('Rabi chamber mismatch')
        frequency_hz=rabi.validate_frequency(frequency_hz)
        from labremote.runtime.characterization_guard import join_completed
        join_completed((self.worker,))
        request=dict(settings=c,frequency_hz=frequency_hz,microwave_control='external',directory=str(Path(directory or Path(__file__).resolve().parents[2]/'data/characterization').expanduser().resolve()))
        with _TASK_LOCK:
            if self.worker.has_requests() or any(t.running() for t in self.worker._background_tasks) or self.worker.waveform_runner.running():raise RuntimeError('FPGA is busy')
            return self.launch(self._execute,(self.worker,),request,parent)

    def _execute(self):
        from labremote.operation.fpga.rabi import run
        from labremote.devices.fpga.adapter import Cancellation
        from labremote.devices.fpga.controller import hd
        c=self.settings['settings'];chamber=c['chamber']
        folder=Path(self.settings['directory'])/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_Rabi_'+chamber+'_'+self.handle.request_id)
        folder.mkdir(parents=True,exist_ok=False)
        config.save(folder/'configuration.json',dict(**self.settings,run_id=self.handle.request_id,fpga=self.worker.name,hardware_definition=hd.__name__,clock_ns=10,source_sha256={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in ('rabi.py','rabi_sequence.py')}))
        points=[];error=None;cleanup_errors=[];frequency=self.settings['frequency_hz']
        self.publish(chamber=chamber,phase='Starting',folder=str(folder),points=0,total=c['N_qubit_control'])
        try:
            with (folder/'raw_fifo.csv').open('w',newline='',encoding='utf-8') as stream:
                writer=csv.writer(stream);writer.writerow(['frequency_hz_metadata','pulse_index','trial','fifo_pulse_index','count','tag','valid'])
                def rows(index,values,valid):
                    writer.writerows([[frequency,index,*r,int(valid)] for r in values]);stream.flush()
                def point(index,counts):
                    points.append(dict(frequency_hz=frequency,index=index,counts=counts))
                    self.publish(phase='Measuring',points=len(points),frequency_hz=frequency,pulse_time_us=index*c['T_mw_step']*.01,
                                 latest_point=dict(frequency_hz=frequency,time_us=index*c['T_mw_step']*.01,population=sum(n>=c['N_threshold'] for n in counts)/len(counts)))
                self.call(DeviceAPI(self.worker,group=self.group)._submit('RABI_ACQUIRE',lambda w:run(w.raw_device.controller,c,Cancellation(),rows,point)))
        except Exception as exc:
            error=exc
            if 'cleanup' in str(exc).lower():cleanup_errors.append(str(exc))
        if self.handle.cancelled() and error is None:error=OperationCancelled('Rabi cancelled')
        status='cancelled' if isinstance(error,OperationCancelled) else 'failed' if error else 'completed'
        report=dict(chamber=chamber,run_id=self.handle.request_id,status=status,folder=str(folder),completed_points=len(points),frequency_hz=frequency,microwave_control='external',error=str(error) if error else '',cleanup_errors=cleanup_errors)
        data=None
        try:
            config.save(folder/'points.json',points)
            data=rabi.analyze(points,c,frequency);config.save(folder/'analysis.json',data)
            with (folder/'population.csv').open('w',newline='',encoding='utf-8') as stream:
                writer=csv.writer(stream);writer.writerow(['frequency_hz_metadata','nominal_pulse_time_us','bright_population','mean_counts','population_sem'])
                for curve in data['curves']:
                    writer.writerows(zip([curve['frequency_hz']]*len(curve['time_us']),curve['time_us'],curve['population'],curve['mean_count'],curve['population_sem']))
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            figure=Figure(figsize=(9,10));FigureCanvasAgg(figure);rabi.draw(figure,data);figure.savefig(folder/'analysis.png',dpi=130)
        except Exception as exc:error=error or exc;report.update(status='failed',error=str(error),analysis_error=str(exc))
        if self.handle.cancelled() and error is None:
            error=OperationCancelled('Rabi cancelled');report.update(status='cancelled',error=str(error))
        config.save(folder/'result.json',report);self.results[chamber]={'report':report,'data':data}
        self.publish(phase=report['status'],result=report,analysis=data)
        if error is not None:raise error
        return report
