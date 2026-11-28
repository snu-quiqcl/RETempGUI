from labremote.runtime.queue_archive import active as queue_archive_active
from labremote.runtime.storage_paths import compact_run_folder
from labremote.devices.fpga.mapping import write_snapshot
from labremote.devices.fpga.mapping import bound_methods
import csv
import hashlib
from datetime import datetime
from pathlib import Path
from labremote.data_paths import characterization_directory
from labremote.api.devices import DeviceAPI
from labremote.runtime.workflow_runner import WorkflowTask, _TASK_LOCK
from labremote.runtime.errors import OperationCancelled
from labremote.experiments.characterization.shared import config; from labremote.experiments.characterization.rabi import model as rabi

@bound_methods('rabi')
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
        request=dict(settings=c,frequency_hz=frequency_hz,microwave_control='external',directory=str(characterization_directory(directory, chamber, 'rabi')))
        with _TASK_LOCK:
            return self.launch(self._execute,(self.worker,),request,parent)

    def _execute(self):
        from labremote.experiments.characterization.rabi.acquisition import run
        from labremote.devices.fpga.adapter import Cancellation
        from labremote.devices.fpga.controller import hd
        c=self.settings['settings'];chamber=c['chamber']
        folder=Path(self.settings['directory'])/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_Rabi_'+chamber+'_'+self.handle.request_id)
        folder=compact_run_folder(folder); folder.mkdir(parents=True,exist_ok=queue_archive_active()); write_snapshot(folder)
        source_paths={'rabi.py':Path(rabi.__file__),'rabi_sequence.py':Path(__file__).with_name('sequence.py'),
                      'detector_comparison.py':Path(__file__).resolve().parents[2]/'detector_comparison.py'}
        config.save(folder/'configuration.json',dict(**self.settings,run_id=self.handle.request_id,fpga=self.worker.name,hardware_definition=hd.__name__,clock_ns=10,source_sha256={name:hashlib.sha256(source_paths[name].read_bytes()).hexdigest() for name in source_paths}))
        from labremote.experiments.characterization.rabi.live import LiveSummary
        live=LiveSummary(c)
        dual=c.get('detector_count',1)==2
        points=[];error=None;cleanup_errors=[];frequency=self.settings['frequency_hz']
        self.publish(chamber=chamber,phase='Starting',folder=str(folder),points=0,total=c['N_qubit_control'])
        try:
            with (folder/'raw_fifo.csv').open('w',newline='',encoding='utf-8') as stream:
                writer=csv.writer(stream)
                writer.writerow(['frequency_hz_metadata','pulse_index','trial',*(['count_pmt1','count_pmt2'] if dual else ['fifo_pulse_index','count']),'tag','valid'])
                def rows(index,values,valid):
                    writer.writerows([[frequency,index,*r,int(valid)] for r in values]);stream.flush()
                def point(index,counts):
                    points.append(dict(frequency_hz=frequency,index=index,counts=counts))
                    self.publish(phase='Measuring',points=len(points),frequency_hz=frequency,pulse_time_us=index*c['T_mw_step']*.01,
                                 live=live.add(dict(index=index,counts=counts,complete=True)),
                                 latest_point=dict(frequency_hz=frequency,time_us=index*c['T_mw_step']*.01,
                                     population=sum(n>=c['N_threshold'] for n in rabi.counts_by_detector(counts)['PMT'])/len(rabi.counts_by_detector(counts)['PMT'])))
                self.call(DeviceAPI(self.worker,group=self.group)._submit('RABI_ACQUIRE',lambda w:run(w.raw_device.controller,c,Cancellation(),rows,point)))
        except Exception as exc:
            error=exc
            if 'cleanup' in str(exc).lower():cleanup_errors.append(str(exc))
        if self.handle.cancelled() and error is None:error=OperationCancelled('Rabi cancelled')
        status='cancelled' if isinstance(error,OperationCancelled) else 'failed' if error else 'completed'
        report=dict(chamber=chamber,run_id=self.handle.request_id,status=status,folder=str(folder),completed_points=len(points),frequency_hz=frequency,microwave_control='external',detector_count=c.get('detector_count',1),error=str(error) if error else '',cleanup_errors=cleanup_errors)
        data=None
        try:
            config.save(folder/'points.json',points)
            data=rabi.analyze(points,c,frequency);config.save(folder/'analysis.json',data)
            with (folder/'population.csv').open('w',newline='',encoding='utf-8') as stream:
                writer=csv.writer(stream)
                writer.writerow((['detector'] if dual else [])+['frequency_hz_metadata','nominal_pulse_time_us','bright_population','mean_counts','population_sem'])
                for curve in data['curves']:
                    rows=zip([curve['frequency_hz']]*len(curve['time_us']),curve['time_us'],curve['population'],curve['mean_count'],curve['population_sem'])
                    writer.writerows(([curve['detector'],*row] if dual else row) for row in rows)
            if not queue_archive_active():
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
