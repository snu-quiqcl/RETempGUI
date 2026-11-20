"""AFG + FPGA scan. No DAC participant, initialization, reads or writes."""
import csv
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
import numpy as np
from labremote.runtime.workflow_runner import WorkflowTask, _TASK_LOCK
from labremote.runtime.jobs import WorkflowGroup
from labremote.runtime.errors import OperationCancelled
from labremote.runtime.storage_paths import compact_run_folder
from labremote.api.devices import DeviceAPI, device_api
from labremote.data_paths import tab_data_directory
from labremote.devices.fpga.mapping import bound_methods, write_snapshot
from labremote.devices.dac.model import atomic_json  # file utility only; no DAC device use
from . import config, model


@bound_methods(None)
class SecularRunner(WorkflowTask):
    def __init__(self,worker):
        super().__init__(worker,'SECULAR_SCAN')
        self.exclusive_fpga=True;self.result=None;self.afg=None

    def start(self,*,settings,afg,directory=None,parent=None):
        from labremote.runtime.characterization_guard import join_completed
        c=config.validate(settings)
        if afg is None or afg.family!='afg2105':raise ValueError('Select a connected AFG2105')
        if c.get('afg_name') and c['afg_name']!=afg.name:raise ValueError('Selected source has changed')
        c['afg_name']=afg.name
        join_completed((self.worker,afg))
        with _TASK_LOCK:
            if self.running():raise RuntimeError('Secular scan is already running')
            self.afg=afg;self.result=None;self.cleanup_group=WorkflowGroup()
            return self.launch(self._execute,(self.worker,afg),
                dict(settings=c,directory=str(tab_data_directory(directory,'micromotion'))),parent)

    def _source(self,label,callback,cleanup=False):
        group=self.cleanup_group if cleanup else self.group
        return self.call(DeviceAPI(self.afg,group=group)._submit('SECULAR_AFG_'+label,callback))

    def _acquire(self,c,frequency,mode,attempts,target,timeout,raw,index,repeat):
        from .acquisition import execute
        from labremote.devices.fpga.adapter import Cancellation
        def rows(values):
            raw.write(json.dumps(dict(point=index,frequency_khz=frequency,kind=mode,repeat=repeat,
                                      received_at=datetime.now().astimezone().isoformat(),rows=values))+'\n')
            raw.flush()
        handle=DeviceAPI(self.worker,group=self.group)._submit('SECULAR_'+mode.upper(),
            lambda w:execute(w.raw_device.controller,c,frequency,Cancellation(),mode,attempts,target,timeout,rows))
        # Cancellation is observed inside acquisition. Wait for STOP/cleanup before releasing resources.
        return self.call(handle)

    def _point(self,c,frequency,raw,point,checkpoint):
        deadline=time.monotonic()+c['point_timeout_s']
        def remaining():
            self.check();value=deadline-time.monotonic()
            if value<=0:raise RuntimeError('Point timeout before target events were reached')
            return value
        point['rates']=[]
        for i in range(c['count_repeats']):
            rate=self._acquire(c,frequency,'count',1,1,remaining(),raw,point['index'],i)
            point['rates'].append(rate);checkpoint('Measuring PMT count rate')
        rates=np.array([v['count']/(v['exposure_us']*1e-6) for v in point['rates']])
        mean=float(rates.mean());sem=float(rates.std(ddof=1)/np.sqrt(len(rates)))
        point.update(mean_rate_cps=mean,rate_sem_cps=sem,background_m=model.background_m(mean,frequency))
        if point['background_m']>c['max_background_m']:
            text=f"Count-rate first-event background M={point['background_m']:.4g} exceeds {c['max_background_m']:g}"
            point['warning']=text
            if c['rate_action']=='stop':raise ValueError(text)
        if mean<=0:raise ValueError('No PMT counts; first-photon fit requires a positive mean rate')
        hist=np.zeros(c['phase_bins'],dtype=np.int64);attempts=events=0;block=0
        while attempts<c['max_attempts'] and events<c['target_events']:
            budget=min(c['block_attempts'],c['max_attempts']-attempts)
            target=min(budget,c['target_events']-events)
            batch=self._acquire(c,frequency,'correlation',budget,target,remaining(),raw,point['index'],block)
            hist+=np.asarray(batch['histogram'],dtype=np.int64)
            attempts+=batch['attempts'];events+=batch['events'];block+=1
            point.update(histogram=hist.tolist(),attempts=attempts,events=events)
            checkpoint('Accumulating SYNC–PMT histogram')
        point['target_reached']=events>=c['target_events']
        point['fit']=config.fit(hist,frequency,mean,sem)
        if not point['target_reached']:
            raise RuntimeError('Maximum attempts reached before target events; partial histogram saved')
        if not point['fit']['valid']:
            raise ValueError('First-photon histogram fit is invalid; raw point saved')
        return point

    def _execute(self):
        c=self.settings['settings'];freqs=config.frequencies(c)
        folder=compact_run_folder(Path(self.settings['directory'])/
            (datetime.now().strftime('%Y%m%d_%H%M%S')+'_secular_'+self.handle.request_id[:8]))
        from labremote.runtime.queue_archive import active as queue_active
        folder.mkdir(parents=True,exist_ok=queue_active());write_snapshot(folder)
        report=dict(schema_version=1,experiment='secular_frequency_scan',settings=c,
            run_id=self.handle.request_id,fpga=self.worker.name,afg=self.afg.name,
            folder=str(folder),status='running',planned_points=len(freqs),points=[],current_point=None,
            started_at=datetime.now().astimezone().isoformat(),cleanup='not_required',
            metadata=dict(afg_amplitude_unit='Vpp',scan_amplitude_unit='dBm',dac='Untouched: no DAC operations',outputs='External FPGA outputs unchanged',
                fit='Conditional first-event multinomial; measured mean rate and SEM',
                phase='r(t)=R[1+M*cos(2*pi*f*t-theta)]; theta=atan2(b,a), radians',
                timing='Stopwatch 1.25 ns; count WAIT n+3 clocks, segmented accumulated live time',
                source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}))
        self.result=report;error=None;reserved=False
        def checkpoint(phase):
            atomic_json(folder/'results.json',config.clean(report))
            self.publish(phase=phase,report=config.clean(report),folder=str(folder))
        try:
            checkpoint('Reserving source')
            self.afg.reserve_scan(self.group.owner);reserved=True
            report['cleanup']='pending'
            self.check()
            def initial(w):
                from labremote.runtime.io import acquire
                return {k:acquire(getattr(w.ps,k)) for k in ('frequency','amplitude','offset','output')}
            report['afg_initial']=self._source('READ',initial)
            self.check()
            report['afg_configured']=self._source('CONFIGURE',lambda w:
                w.raw_device.configure_sine(freqs[0]*1000,(0.4*10**(c['amplitude_dbm']/10))**0.5,c['offset_v']))
            self.call(device_api(self.afg,group=self.group).on())
            with (folder/'raw_fifo.jsonl').open('w',encoding='utf-8') as raw:
                for index,frequency in enumerate(freqs):
                    self.check()
                    self.call(device_api(self.afg,group=self.group).set_frequency(frequency*1000))
                    actual=float(self.call(device_api(self.afg,group=self.group).acquire('frequency')))/1000
                    model._geometry(actual,c['phase_bins']);self.wait(c['settle_s'])
                    point=dict(index=index,requested_frequency_khz=frequency,frequency_khz=actual,
                        status='acquiring',events=0,attempts=0,histogram=[0]*c['phase_bins'])
                    report['current_point']=point;checkpoint('Measuring frequency')
                    self._point(c,actual,raw,point,checkpoint)
                    point['status']='complete';report['points'].append(point)
                    atomic_json(folder/f'point_{index:05d}.json',config.clean(point))
                    report['current_point']=None;checkpoint('Point complete')
        except Exception as exc:error=exc
        finally:
            if reserved:
                try:
                    # Cleanup group is uncancelled but retains the same device owner.
                    self.call(device_api(self.afg,group=self.cleanup_group).off())
                    report['cleanup']='afg_output_off'
                except Exception as exc:
                    report['cleanup']='failed';report['cleanup_error']=str(exc);error=error or exc
                finally:self.afg.release_scan(self.group.owner)
            if self.handle.cancelled() and error is None:error=OperationCancelled('Secular scan cancelled')
            report.update(status='failed' if report['cleanup']=='failed' else
                          'cancelled' if isinstance(error,OperationCancelled) else 'failed' if error else 'completed',
                          error=str(error) if error else '',finished_at=datetime.now().astimezone().isoformat())
            if report['current_point'] is not None:
                report['current_point']['status']=report['status']
                atomic_json(folder/'partial_point.json',config.clean(report['current_point']))
            checkpoint(report['status'])
            try:
                self._export(folder,report)
            except Exception as exc:
                report['export_error']=str(exc);checkpoint(report['status'])
        if error:raise error
        return report

    def _export(self,folder,report):
        with (folder/'frequency_scan.csv').open('w',newline='',encoding='utf-8') as stream:
            writer=csv.writer(stream);writer.writerow(['frequency_khz','mean_rate_cps','rate_sem_cps',
                'events','attempts','modulation','modulation_se','phase_rad','phase_se','fit_valid'])
            for p in report['points']:
                fit=p['fit'];writer.writerow([p[k] for k in ('frequency_khz','mean_rate_cps','rate_sem_cps','events','attempts')]+
                    [fit[k] for k in ('modulation','modulation_se','phase_rad','phase_se','valid')])
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from .plotting import draw
        figure=Figure(figsize=(11,7));FigureCanvasAgg(figure);draw(figure,report)
        figure.savefig(folder/'secular_scan.png',dpi=150)
