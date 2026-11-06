"""Own FPGA and DAC queues for a complete scan, including restoration and leases."""
import json
import hashlib
import shutil
import time
from datetime import datetime
from pathlib import Path
import numpy as np
from labremote.runtime.workflow_runner import WorkflowTask, _TASK_LOCK
from labremote.runtime.jobs import WorkflowGroup
from labremote.runtime.errors import OperationCancelled
from labremote.api.devices import DeviceAPI
from labremote.data_paths import tab_data_directory
from labremote.devices.dac.model import VoltageSet, atomic_json
from labremote.operation.dac.timing import ManualTiming
from labremote.operation.dac.set_voltages import set_voltages
from . import config, analysis


class MicromotionRunner(WorkflowTask):
    def __init__(self, worker):
        super().__init__(worker,'MICROMOTION')
        self.exclusive_fpga=True
        self.result=None
        self.session=None
        self.dac=None

    def start(self, *, settings, mode='scan', dac=None, directory=None, candidate=None, parent=None):
        from labremote.runtime.characterization_guard import join_completed
        c=config.validate(settings)
        if mode not in ('input','correlation','scan','apply'):raise ValueError('Invalid micromotion mode')
        if mode=='input' and not c['counter_pin']:raise ValueError('Select and wire the separate RF counter input first')
        participants=(self.worker,)
        if mode in ('scan','apply'):
            if dac is None or dac.family!='dac':raise ValueError('Select a connected DAC')
            participants+=(dac,)
        if mode=='apply':
            if candidate is None or len(candidate)!=2:raise ValueError('Select a compensation-line voltage')
            for value,spec in zip(candidate,(c['left'],c['right'])):
                if not np.isfinite(value) or not spec[0]<=value<=spec[1]:
                    raise ValueError('Candidate must be inside the measured voltage rectangle')
        join_completed(participants)
        with _TASK_LOCK:
            for w in participants:
                if w.has_requests() or any(t.running() for t in w._background_tasks) or (
                    hasattr(w,'waveform_runner') and w.waveform_runner.running()):raise RuntimeError('Device busy: '+str(w.name))
            self.dac=dac if mode in ('scan','apply') else None
            self.session=None;self.result=None;self.cleanup_group=WorkflowGroup()
            return self.launch(self._execute,participants,dict(settings=c,mode=mode,candidate=candidate,
                directory=str(tab_data_directory(directory,'micromotion'))),parent)

    def _dac_call(self, label, callback, cleanup=False):
        return self.call(DeviceAPI(self.dac,group=self.cleanup_group if cleanup else self.group)._submit(
            'MM_DAC_'+label,callback))

    def _begin_dac(self,w):
        from labremote.runtime.jobs import CURRENT_JOB
        w._check_cancelled(CURRENT_JOB.get())
        status=w.synchronize()
        if w.config.device!=self.settings['settings']['chamber']:
            raise ValueError('DAC chamber does not match micromotion chamber')
        if status.get('shared_control_version',0)<1:raise ValueError('DAC shared control API required')
        if not {'L_IN','R_IN'}<=set(w.config.by_id):raise ValueError('DAC map must contain L_IN and R_IN')
        baseline=dict(status['last_sent'])
        # Validate every scan-axis value with the actual channel calibration/range.
        c=self.settings['settings']
        for eid,spec in (('L_IN',c['left']),('R_IN',c['right'])):
            for value in config.grid(spec):VoltageSet.from_values(w.config,{**baseline,eid:float(value)})
        token=w.raw_device.acquire_control(w.configuration_id)
        # Capture inside owning callback: cancellation after acquire must still release it.
        self.session=dict(token=token,baseline=baseline,changed=False,configuration_id=w.configuration_id,
                          configuration=w.config.as_dict())
        w.control_token=token
        # Re-snapshot after the lease closes the race with another client's write.
        self.session['baseline']=dict(w.synchronize()['last_sent'])
        self.renewed=time.monotonic()

    def _renew(self, force=False):
        if self.dac is not None and self.session and (force or time.monotonic()-self.renewed>=3):
            def renew(w):
                from labremote.runtime.jobs import CURRENT_JOB
                w._check_cancelled(CURRENT_JOB.get())
                return w.raw_device.renew_control(self.session['token'])
            self._dac_call('RENEW',renew)
            self.renewed=time.monotonic()

    def _voltage(self,w,voltages):
        if w.configuration_id!=self.session['configuration_id']:
            raise RuntimeError('DAC configuration changed during micromotion scan')
        w.raw_device.renew_control(self.session['token'])
        state=VoltageSet.from_values(w.config,{**self.session['baseline'],
            'L_IN':float(voltages[0]),'R_IN':float(voltages[1])})
        self.session['changed']=True  # A failed transport may still have applied a write.
        # Only these two electrodes are transmitted; all other outputs are untouched.
        return set_voltages(w,state,self.settings['settings']['use_ldac'],ManualTiming(),
            electrode_ids=('L_IN','R_IN'))

    def _finish_dac(self,w,restore):
        session=self.session;error=None
        try:
            if restore and session['changed']:
                self._voltage(w,[session['baseline']['L_IN'],session['baseline']['R_IN']])
        except Exception as exc:error=exc
        finally:
            try:w.raw_device.release_control(session['token'])
            except Exception as exc:error=error or exc
            w.control_token=None
            try:w.refresh()
            except Exception as exc:error=error or exc
        if error:raise RuntimeError('DAC restore/release unconfirmed: '+str(error)) from error

    def _settle(self,seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            self.wait(min(.1,max(0,end-time.monotonic())));self._renew()

    def _acquire(self,c,mode,target,raw):
        from .acquisition import execute
        from labremote.devices.fpga.adapter import Cancellation
        def rows(values):
            raw.write(json.dumps(dict(received_at=datetime.now().astimezone().isoformat(),rows=values))+'\n');raw.flush()
        handle=DeviceAPI(self.worker,group=self.group)._submit('MM_ACQUIRE',
            lambda w:execute(w.raw_device.controller,c,Cancellation(),mode,target,rows))
        try:
            while not handle.done.wait(.1):
                self.check();self._renew()
            return self.call(handle)
        except Exception:
            self.group.stop.set()
            # Never release DAC / return while FPGA is still acquiring.
            try:handle.wait()
            except Exception:pass
            raise

    def _point(self,c,raw,on_batch):
        started=time.monotonic();hist=np.zeros(config.bins(c),dtype=np.int64);attempts=0
        target=c['events']*c['batches'];accepted=0
        while accepted<target:
            self.check();self._renew()
            remaining=c['timeout_s']-(time.monotonic()-started)
            if remaining<=0:raise RuntimeError('Point timeout: insufficient accepted RF-photon events')
            batch=self._acquire(dict(c,timeout_s=remaining),'correlation',min(30000,target-accepted),raw)
            hist+=np.asarray(batch['histogram'],dtype=np.int64);attempts+=batch['attempts'];accepted+=batch['accepted']
            on_batch(dict(histogram=hist.tolist(),accepted=accepted,attempts=attempts,elapsed_s=time.monotonic()-started))
        result=dict(histogram=hist.tolist(),accepted=accepted,attempts=attempts,elapsed_s=time.monotonic()-started)
        result['fit']=analysis.fit_histogram(hist,c)
        return result

    def _execute(self):
        c=self.settings['settings'];mode=self.settings['mode']
        folder=Path(self.settings['directory'])/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+c['chamber']+'_'+self.handle.request_id[:8])
        folder.mkdir(parents=True,exist_ok=False)
        source=folder/'source';source.mkdir()
        paths=list(Path(__file__).parent.glob('*.py'))+[Path(config.hd.__file__),
            Path(config.hd.__file__).with_name('HardwareDefinition_v4_04.py')]
        hashes={}
        for path in paths:
            shutil.copyfile(path,source/path.name)
            hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
        report=dict(schema_version=1,experiment='micromotion',mode=mode,settings=c,
            run_id=self.handle.request_id,fpga=self.worker.name,dac=self.dac.name if self.dac else None,
            status='running',started_at=datetime.now().astimezone().isoformat(),folder=str(folder),
            points=[],valley=dict(valid=False,reason='Waiting for measured points'),
            cleanup='not_required',current_point=None,rf_test=None,
            metadata=dict(source_sha256=hashes,stopwatch_bin_ns=1.25,sequencer_clock_ns=10,outputs='Unchanged; no mode switching',
                pins={k:config.PINS.get(c[k]) for k in ('trg_pin','pmt_pin','counter_pin')},
                voltage_readback='DAC last-requested voltages, not physical readback',
                analysis='Poisson IRLS harmonic quadratures; weighted rank-one affine valley; local linearized CI'))
        self.result=report
        error=None
        def checkpoint(phase):
            atomic_json(folder/'results.json',report)
            self.publish(phase=phase,report=report,folder=str(folder))
        checkpoint('Starting')
        try:
            if self.dac:
                self._dac_call('RESERVE',self._begin_dac)
                report['dac_initial']=self.session['baseline'];report['dac_configuration']=self.session['configuration']
                report['cleanup']='pending'
                checkpoint('DAC reserved')
            with (folder/'raw_fifo.jsonl').open('w',encoding='utf-8') as raw:
                if mode=='input':
                    report['rf_test']=self._acquire(c,'input',1,raw)
                else:
                    points=[(None,None)] if mode=='correlation' else (
                        [tuple(self.settings['candidate'])] if mode=='apply' else
                        [(float(x),float(y)) for x in config.grid(c['left']) for y in config.grid(c['right'])])
                    report['planned_points']=len(points)
                    for index,(x,y) in enumerate(points):
                        self.check()
                        report['current_point']=dict(index=index,left=x,right=y,status='acquiring')
                        checkpoint('Point '+str(index+1))
                        if self.dac:
                            self._dac_call('SET',lambda w,x=x,y=y:self._voltage(w,(x,y)))
                            self._settle(c['settle_s'])
                        def partial(data):
                            report['current_point'].update(data)
                            atomic_json(folder/f'partial_{index:05d}.json',report['current_point'])
                            self.publish(phase='Acquiring',report=report,folder=str(folder))
                        point=dict(index=index,left=x,right=y,**self._point(c,raw,partial))
                        report['points'].append(point)
                        atomic_json(folder/f'point_{index:05d}.json',point)
                        report['current_point']=None
                        if mode=='scan':
                            self._renew(force=True)
                            report['valley']=analysis.fit_valley(report['points'])
                        checkpoint('Measured '+str(index+1))
        except Exception as exc:
            error=exc
        finally:
            if self.session:
                restore=mode!='apply' or error is not None or self.handle.cancelled()
                try:
                    self._dac_call('RESTORE_RELEASE',lambda w:self._finish_dac(w,restore),cleanup=True)
                    report['cleanup']='restored' if restore else 'candidate_retained'
                except Exception as exc:
                    report['cleanup']='failed';report['cleanup_error']=str(exc)
                    error=error or exc
            if self.handle.cancelled() and error is None:error=OperationCancelled('Micromotion cancelled')
            report.update(status='cancelled' if isinstance(error,OperationCancelled) else 'failed' if error else 'completed',
                error=str(error) if error else '',finished_at=datetime.now().astimezone().isoformat())
            checkpoint(report['status'])
            try:
                from matplotlib.figure import Figure
                from matplotlib.backends.backend_agg import FigureCanvasAgg
                from .plotting import draw
                figure=Figure(figsize=(12,10));FigureCanvasAgg(figure);draw(figure,report)
                figure.savefig(folder/'micromotion.png',dpi=150)
            except Exception as exc:
                report['plot_export_error']=str(exc);checkpoint(report['status'])
        if error:raise error
        return report
