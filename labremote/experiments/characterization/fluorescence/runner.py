from labremote.runtime.queue_archive import active as queue_archive_active
from labremote.runtime.storage_paths import compact_run_folder
from labremote.devices.fpga.mapping import write_snapshot
from labremote.devices.fpga.mapping import bound_methods
import csv
import hashlib
import time
from datetime import datetime
from pathlib import Path
from labremote.data_paths import characterization_directory
import numpy as np
from labremote.runtime.workflow_runner import WorkflowTask, _TASK_LOCK
from labremote.runtime.errors import OperationCancelled
from labremote.api.devices import DeviceAPI
from labremote.experiments.characterization.shared.config import prepare, save


@bound_methods('fluorescence')
class FluorescenceRunner(WorkflowTask):
    def __init__(self,worker):
        super().__init__(worker,'FLUORESCENCE');self.exclusive_fpga=True;self.results={}

    def start(self,chamber,*,settings=None,settings_file=None,mapping_file=None,directory=None,parent=None):
        if self.handle is not None and self.handle.done.is_set():self.join()
        from labremote.runtime.characterization_guard import join_completed
        join_completed((self.worker,))
        request=prepare(chamber,settings,settings_file,mapping_file)
        request['directory']=str(characterization_directory(directory, chamber, 'fluorescence'))
        with _TASK_LOCK:
            return self.launch(self._execute,(self.worker,),request,parent)

    def _execute(self):
        from labremote.experiments.characterization.fluorescence.model import analyze, draw
        from labremote.experiments.characterization.fluorescence.acquisition import acquire
        from labremote.devices.fpga.adapter import Cancellation
        chamber=self.settings['settings']['chamber'];config=self.settings['settings'];route=self.settings['mapping']['routes'][chamber]
        folder=Path(self.settings['directory'])/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+chamber+'_'+self.handle.request_id)
        folder=compact_run_folder(folder); folder.mkdir(parents=True,exist_ok=queue_archive_active()); write_snapshot(folder)
        source_paths={'fluorescence.py':Path(__file__).with_name('model.py'),
                      'config.py':Path(__file__).resolve().parents[1]/'shared/config.py'}
        metadata={**self.settings,'run_id':self.handle.request_id,'fpga':self.worker.name,
                  'analysis_timebase':'Nominal exposure spacing; inter-batch host gaps excluded',
                  'source_sha256':{name:hashlib.sha256(source_paths[name].read_bytes()).hexdigest() for name in ('fluorescence.py','config.py')}}
        save(folder/'configuration.json',metadata)
        counts=[];error=None;status='completed';started=time.monotonic();batches=0
        self.publish(chamber=chamber,folder=str(folder),phase='Acquiring',samples=0,total=config['num_average']*config['num_repeat'],pmt=route['PMT'])
        with (folder/'raw_fifo.csv').open('w',newline='',encoding='utf-8') as stream:
            writer=csv.writer(stream);writer.writerow(['batch','sample_index','exposure_ticks_100us','count','tag','valid'])
            def rows(batch,values,valid):
                writer.writerows([[batch,*row,int(valid)] for row in values]);stream.flush()
                if valid:counts.extend(row[2] for row in values)
            def batch_done(number):
                nonlocal batches
                batches=number
                data=analyze(counts,config['exposure_ms'])
                report=dict(chamber=chamber,run_id=self.handle.request_id,status='Acquiring',
                            completed_batches=number,samples=len(counts),summary=data['summary'])
                self.publish(batches=number,samples=len(counts),elapsed_s=time.monotonic()-started,
                             analysis=data,result=report)
            try:
                self.call(DeviceAPI(self.worker,group=self.group)._submit('FLUORESCENCE_ACQUIRE',
                    lambda w:acquire(w.raw_device.controller,config,route,Cancellation(),rows,batch_done)))
            except Exception as exc:error=exc;status='cancelled' if isinstance(exc,OperationCancelled) else 'failed'
        report=dict(chamber=chamber,run_id=self.handle.request_id,status=status,folder=str(folder),samples=len(counts),
                    expected_samples=config['num_average']*config['num_repeat'],completed_batches=batches,error=str(error) if error else '')
        data=None
        try:
            if counts:
                self.publish(phase='Analyzing / saving')
                data=analyze(counts,config['exposure_ms']);report['summary']=data['summary']
                np.savez_compressed(folder/'analysis.npz',**{k:v for k,v in data.items() if k!='summary'})
                np.savetxt(folder/'time_trace.csv',np.column_stack((data['time_ms']*1000,data['counts'])),delimiter=',',header='time_us,counts',comments='')
                np.savetxt(folder/'histogram.csv',np.column_stack((data['histogram_x'],data['histogram'],data['poisson'])),delimiter=',',header='count,occurrences,poisson_expected',comments='')
                np.savetxt(folder/'fft.csv',np.column_stack((data['frequency_hz'],data['power'])),delimiter=',',header='frequency_Hz,power',comments='')
                if not queue_archive_active():
                    from matplotlib.figure import Figure
                    from matplotlib.backends.backend_agg import FigureCanvasAgg
                    figure=Figure(figsize=(9,10));FigureCanvasAgg(figure);draw(figure,data);figure.savefig(folder/'analysis.png',dpi=130)
        except Exception as exc:
            error=error or exc;report.update(status='failed',error=str(error),analysis_error=str(exc))
        if self.handle.cancelled() and error is None:
            error=OperationCancelled('Fluorescence cancelled');report.update(status='cancelled',error=str(error))
        save(folder/'result.json',report)
        self.results[chamber]={'report':report,'data':data}
        self.publish(phase=report['status'],samples=len(counts),result=report,analysis=data)
        if error is not None:raise error
        return report
