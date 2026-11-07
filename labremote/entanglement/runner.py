import csv
import hashlib
import os
import time
import shutil
from datetime import datetime
from pathlib import Path
from labremote.data_paths import tab_data_directory
from labremote.runtime.workflow_runner import WorkflowTask, _TASK_LOCK
from labremote.runtime.errors import OperationCancelled
from labremote.api.devices import DeviceAPI
from . import config
from .plotting import Accumulator, EntanglementPlot
from .storage import measurement


class EntanglementRunner(WorkflowTask):
    def __init__(self,worker):
        super().__init__(worker,'ENTANGLEMENT'); self.exclusive_fpga=True; self.result=None

    def start(self,*,settings=None,settings_file=None,directory=None,parent=None):
        from labremote.runtime.characterization_guard import join_completed
        join_completed((self.worker,))
        if settings is not None and settings_file is not None:raise ValueError('Choose settings or settings_file')
        c=config.load(settings_file) if settings is None else config.validate(settings)
        with _TASK_LOCK:
            if self.worker.has_foreground_requests() or self.worker.waveform_runner.running() or any(t.running() for t in self.worker._background_tasks):raise RuntimeError('FPGA busy')
            return self.launch(self._execute,(self.worker,),dict(settings=c,directory=str(tab_data_directory(directory,'entanglement'))),parent)

    def _execute(self):
        from labremote.devices.fpga.adapter import Cancellation
        from .acquisition import run
        started_at=datetime.now().astimezone().isoformat(timespec='milliseconds'); run_clock=time.perf_counter()
        c=self.settings['settings']; folder=Path(self.settings['directory'])/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_Entanglement_'+self.handle.request_id[:8])
        folder.mkdir(parents=True,exist_ok=False); source=folder/'source'; source.mkdir()
        files={p.name:p for p in Path(__file__).parent.glob('*.py')}
        files['entanglement_tab.py']=Path(__file__).resolve().parents[1]/'ui/entanglement_tab.py'
        # Queue archives its own workflow.py; standalone must not require that wrapper.
        files['decay_fit_source.py']=Path(__file__).resolve().parents[1]/'decay/plotting.py'
        files['hardware_definition.py']=Path(config.hd.__file__)
        files['HardwareDefinition_v4_04.py']=Path(config.hd.__file__).with_name('HardwareDefinition_v4_04.py')
        files['SequencerProgram_v1_08.py']=Path(config.hd.__file__).with_name('SequencerProgram_v1_08.py')
        files['SequencerUtility_v1_03.py']=Path(config.hd.__file__).with_name('SequencerUtility_v1_03.py')
        hashes={}
        for name,path in files.items():shutil.copyfile(path,source/name); hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        metadata=dict(settings=c,resolved_outputs=config.resolved_outputs(c),resolved_inputs=dict(config.hd.input_mapping),phase=config.phase_values(c),cleanup_outputs=config.CLEANUP_LEVELS,mw_source_control="external workflow/manual; no generator commands",run_id=self.handle.request_id,fpga=self.worker.name,source_sha256=hashes,sequencer_clock_ns=10,stopwatch_bin_ns=1.25,
            arrival_histogram_scope='All stopwatch arrivals in [0,120) bins, including before cutoff; FIFO protocol 2. No individual photon-pair records.',
            normalization='Decay counts integrate each channel from its own cutoff through bin 119, divided by actual attempted trials. No SYNC validation. Herald probability = successes / all completed-batch attempts, including exhausted batches. Aborted/failed batches excluded. Bright iff counts > configured per-ion threshold. Geometric distribution uses attempt counts and logarithmic bins, not PC wall time.',
            timing_note='Timezone-aware PC timestamps; durations use a monotonic clock. Communication timings measure host API calls including software/driver overhead (upload includes encoding); not pure wire latency or FPGA photon event timestamps.')
        acc=Accumulator(c); error=None; cleanup_status='unknown'; batch_records=[]; fits={}
        report=dict(schema_version=2,experiment='entanglement',run_id=self.handle.request_id,folder=str(folder),
            started_at=started_at,finished_at=None,elapsed_s=0.,status='running',error='',
            completed_batches=0,expected_batches=c['batches'],batch_in_progress=None,aborted_batches=0,
            cleanup_status='unknown',continue_allowed=False)
        def checkpoint():
            data=acc.data()
            report.update(completed_batches=len(acc.batches),elapsed_s=time.perf_counter()-run_clock,
                metrics=data['metrics'],cleanup_status=cleanup_status,aborted_batches=sum(b['status']=='aborted' for b in batch_records))
            final=measurement(data,c)
            final.update(completed_batches=len(acc.batches))
            if fits:final['decay_fit']=fits
            config.save(folder/'results.json',dict(report,configuration=metadata,
                axes=dict(decay_time_ns=[i*1.25 for i in range(120)],
                          coincidence_delay_ns=[(i-120)*1.25 for i in range(240)]),
                batches=batch_records,final=final))
        def cleaned(status):
            nonlocal cleanup_status
            cleanup_status=status
        self.publish(phase='Starting',folder=str(folder),total=c['batches'],live=acc.data())
        checkpoint()
        try:
            with (folder/'raw_fifo.csv').open('w',newline='',encoding='utf-8') as raw:
                writer=csv.writer(raw); writer.writerow(['run_id','batch','row_index','received_at','word0','word1','word2','tag','structurally_valid','raw_record'])
                raw.flush(); row_indices={}
                def rows(batch,values,valid):
                    received_at=datetime.now().astimezone().isoformat(timespec='milliseconds')
                    for row in values if isinstance(values,list) else [values]:
                        index=row_indices.get(batch,0); row_indices[batch]=index+1
                        shaped=isinstance(row,(tuple,list)) and len(row)==4
                        writer.writerow([self.handle.request_id,batch,index,received_at,*(list(row) if shaped else ['']*4),int(valid),'' if shaped else repr(row)])
                    raw.flush()
                def received(b):
                    acc.add(b);single=Accumulator(c);single.add(b)
                    summary=measurement(single.data(),c)
                    batch_records[-1].update(measurement=b,decay_fit=summary['decay_fit'],histogram=summary['histogram'],decay_counts=summary['decay_counts'],probabilities=summary['metrics'],
                        actual_trials=summary['actual_trials'],decay_counts_per_actual_trial=summary['decay_counts_per_actual_trial'],
                        decay_reference=summary['decay_reference'],state_readout_histograms=summary['state_readout_histograms'])
                    self.publish(phase='Measuring',live=acc.data(),completed_batches=len(acc.batches))
                def batch_event(event):
                    event=dict(event,run_id=self.handle.request_id); kind=event.pop('event')
                    if kind=='started':
                        batch_records.append(event); report['batch_in_progress']=event['batch']
                    else:
                        batch_records[-1].update(event); report['batch_in_progress']=None
                    raw.flush(); os.fsync(raw.fileno()); checkpoint()
                    self.publish(aborted_batches=report['aborted_batches'],batch_in_progress=report['batch_in_progress'])
                self.call(DeviceAPI(self.worker,group=self.group)._submit('ENTANGLEMENT_ACQUIRE',
                    lambda w:run(w.raw_device.controller,c,Cancellation(),rows,received,cleaned,on_event=batch_event)))
        except Exception as exc:
            error=exc
        data=acc.data()
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            fig=Figure(figsize=(14,15)); FigureCanvasAgg(fig); plot=EntanglementPlot(fig,c); plot.update(data)
            fits=plot.fits; fig.savefig(folder/'entanglement.png',dpi=150)
        except Exception as exc:error=error or exc
        if self.handle.cancelled() and error is None:error=OperationCancelled('ENTANGLEMENT cancelled')
        report.update(status='cancelled' if isinstance(error,OperationCancelled) else 'failed' if error else 'completed',
            error=f'{type(error).__name__}: {error}' if error else '',finished_at=datetime.now().astimezone().isoformat(timespec='milliseconds'),
            continue_allowed=cleanup_status=='completed' and not isinstance(error,(ConnectionError,TimeoutError)))
        checkpoint(); self.result=dict(report=report,data=data,settings=c)
        self.publish(phase=report['status'],result=report,live=data,aborted_batches=report['aborted_batches'])
        if error:raise error
        return report
