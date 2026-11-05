import csv
import hashlib
import os
import time
from pathlib import Path
from labremote.data_paths import decay_directory
from datetime import datetime
from labremote.runtime.workflow_runner import WorkflowTask,_TASK_LOCK
from labremote.runtime.errors import OperationCancelled
from labremote.api.devices import DeviceAPI
from . import config
from .plotting import Accumulator,DecayPlot
from .storage import measurement

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
            return self.launch(self._execute,(self.worker,),dict(settings=c,directory=str(decay_directory(directory, chamber, mode))),parent)
    def _execute(self):
        from labremote.devices.fpga.adapter import Cancellation
        from labremote.devices.fpga.controller import hd
        from labremote.operation.fpga.decay import run
        c=self.settings['settings'];run_id=self.handle.request_id
        started_at=datetime.now().astimezone().isoformat(timespec='milliseconds');run_clock=time.monotonic()
        folder=Path(self.settings['directory'])/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_Decay_'+c['chamber']+'_'+c['mode']+'_'+run_id)
        folder.mkdir(parents=True,exist_ok=False)
        source_paths={name:Path(__file__).parent/name for name in ('config.py','sequence.py','runner.py','plotting.py','storage.py')}
        source_paths.update(operation=Path(__file__).resolve().parents[1]/'operation/fpga/decay.py',
            hardware_definition=Path(hd.__file__),hardware_base=Path(hd.__file__).with_name('HardwareDefinition_v4_04.py'))
        metadata=dict(settings=c,fpga=self.worker.name,hardware_definition=hd.__name__,
            sequencer_clock_ns=10,stopwatch_bin_ns=1.25,
            time_settings_us={key:config.time_to_display(key,c[key]) for key in config.TIME_LABELS},
            source_sha256={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in source_paths.items()},
            acquisition_note='One FPGA execution per zero-based PC batch; 16-bit histogram bins; SYNC arrival required.',
            trials_note='programmed_trials is configured repetitions, not observed valid SYNC or photon events.',
            timestamp_note='Timezone-aware PC timestamps. Batch start includes preparation; sequencer_started_at follows the start command; finish includes FIFO reception. Not FPGA event timestamps.',
            raw_note='row_index is zero-based within each batch; valid describes the received packet, not completeness of the entire batch.')
        acc=Accumulator(c);error=None;batch_records=[]
        report=dict(schema_version=3,experiment='decay',chamber=c['chamber'],mode=c['mode'],run_id=run_id,
            folder=str(folder),started_at=started_at,finished_at=None,elapsed_s=0.,status='running',error='',
            completed_batches=0,expected_batches=c['outer_loop'],failed_batches=0,cancelled_batches=0,
            batch_in_progress=None)
        def checkpoint():
            data=acc.data();report['completed_batches']=len(data['batches'])
            report['elapsed_s']=time.monotonic()-run_clock
            final=measurement(data['counts'],data['trials'],c)
            final['completed_batches']=len(data['batches'])
            config.save(folder/'results.json',dict(report,configuration=metadata,
                axes=dict(decay_time_ns=[i*1.25 for i in range(c['MAX_TIME_DIFFERENCE'])]),batches=batch_records,final=final))
        self.publish(chamber=c['chamber'],mode=c['mode'],phase='Starting',folder=str(folder),total=c['outer_loop'])
        checkpoint()
        try:
            with (folder/'raw_fifo.csv').open('w',newline='',encoding='utf-8') as raw:
                writer=csv.writer(raw);writer.writerow(['run_id','batch','row_index','received_at','fifo_0','fifo_1','fifo_2','tag','valid','raw_record'])
                raw.flush();row_indices={}
                def rows(batch,chunk,values,valid):
                    received_at=datetime.now().astimezone().isoformat(timespec='milliseconds')
                    records=values if isinstance(values,list) else [values]
                    for row in records:
                        index=row_indices.get(batch,0);row_indices[batch]=index+1
                        shaped=isinstance(row,(list,tuple)) and len(row)==4
                        fields=list(row) if shaped else ['']*4
                        writer.writerow([run_id,batch,index,received_at,*fields,int(valid),'' if shaped else repr(row)])
                    raw.flush()
                def received(chunk):
                    acc.add(chunk)
                    self.publish(phase='Measuring',live=acc.data(),completed_batches=len(acc.batches))
                def batch_event(event):
                    event=dict(event,run_id=run_id)
                    kind=event.pop('event')
                    if kind=='started':
                        report['batch_in_progress']=event['batch'];batch_records.append(event)
                    else:
                        report['batch_in_progress']=None
                        if event['status']=='completed':
                            data=acc.batches[event['batch']]
                            event.update(measurement(data['histograms'],data['trials'],c))
                        elif event['status']=='failed':report['failed_batches']+=1
                        elif event['status']=='cancelled':report['cancelled_batches']+=1
                        batch_records[-1].update(event)
                    raw.flush();os.fsync(raw.fileno())
                    checkpoint()
                self.call(DeviceAPI(self.worker,group=self.group)._submit('DECAY_ACQUIRE',
                    lambda w:run(w.raw_device.controller,c,Cancellation(),rows,received,on_batch=batch_event)))
        except Exception as exc:error=exc
        data=acc.data()
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            fig=Figure(figsize=(14,12));FigureCanvasAgg(fig);plot=DecayPlot(fig,c)
            plot.update(data)  # Retain fitting in the figure, without serializing fit parameters.
            fig.savefig(folder/'decay.png',dpi=160)
        except Exception as exc:error=error or exc
        if self.handle.cancelled() and error is None:error=OperationCancelled('Decay cancelled')
        report.update(status='cancelled' if isinstance(error,OperationCancelled) else 'failed' if error else 'completed',
            error=f'{type(error).__name__}: {error}' if error else '',finished_at=datetime.now().astimezone().isoformat(timespec='milliseconds'))
        checkpoint();self.results[c['chamber'],c['mode']]=dict(report=report,data=data,settings=c)
        self.publish(phase=report['status'],result=report,live=data)
        if error:raise error
        return report
