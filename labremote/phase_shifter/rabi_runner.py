"""Two-dimensional phase/time acquisition through the owned FPGA queue."""
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from labremote.devices.fpga.mapping import bound_methods, write_snapshot
from labremote.runtime.workflow_runner import WorkflowTask, _TASK_LOCK
from labremote.runtime.characterization_guard import join_completed
from labremote.runtime.errors import OperationCancelled
from labremote.api.devices import DeviceAPI
from labremote.devices.fpga.adapter import Cancellation
from labremote.data_paths import tab_data_directory
from . import config, rabi, acquisition


@bound_methods(None)
class PhaseRabiRunner(WorkflowTask):
    def __init__(self, worker):
        super().__init__(worker,'PHASE_SHIFTER_RABI')
        self.exclusive_fpga=True

    def start(self, settings, directory=None, parent=None):
        join_completed((self.worker,))
        c,phases,times,skipped=rabi.validate(settings)
        with _TASK_LOCK:
            if self.worker.has_requests() or self.worker.waveform_runner.running() or any(t.running() for t in self.worker._background_tasks):
                raise RuntimeError('다른 FPGA 작업이 끝난 뒤 실행하세요.')
            return self.launch(self._execute,(self.worker,),dict(settings=c,phases=phases,times=times,
                skipped=skipped,directory=str(tab_data_directory(directory,'phase_rabi'))),parent=parent)

    def _execute(self):
        c=self.settings['settings']; phases=self.settings['phases']; times=self.settings['times']
        folder=Path(self.settings['directory'])/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_phase_rabi_'+self.handle.request_id[:8])
        folder.mkdir(parents=True,exist_ok=False);write_snapshot(folder)
        source=folder/'source';source.mkdir()
        for p in Path(__file__).parent.glob('*.py'):shutil.copyfile(p,source/p.name)
        shutil.copyfile(config.hd.__file__,source/'hardware_definition.py')
        if c.get('calibration'):
            suffix='json' if c['calibration'].get('kind')=='ramsey_data_interpolation' else 'csv'
            (source/('calibration.'+suffix)).write_text(c['calibration']['csv'],encoding='utf-8')
        plan=[dict(p,phase_index=i,time_index=j,pulse_clocks=t) for i,p in enumerate(phases) for j,t in enumerate(times)]
        points=[];fits=[]
        report=dict(schema_version=1,experiment='phase_rabi',settings=c,phases=phases,pulse_clocks=times,
            skipped_angles=self.settings['skipped'],points=points,fits=fits,folder=str(folder),status='running',
            started_at=datetime.now().astimezone().isoformat(),
            phase_note='Requested angle and nominal/conditional estimate; actual emitted RF phase is not measured')
        def checkpoint():
            p=folder/'result.tmp';p.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');p.replace(folder/'result.json')
        checkpoint()
        self.publish(points=[],fits=[],phases=phases,times=times,total=len(plan),folder=str(folder),phase='측정 중')
        error=None
        try:
            with (folder/'raw_fifo.csv').open('w',newline='',encoding='utf-8') as f:
                writer=csv.writer(f);writer.writerow(['phase_index','time_index','requested_angle_deg','requested_code','pulse_clocks','shot','actual_code','photons','tag'])
                def received(code,rows):
                    target=plan[len(points)]
                    writer.writerows([target['phase_index'],target['time_index'],target['requested_angle_deg'],code,target['pulse_clocks'],*row] for row in rows);f.flush()
                def point(value):
                    target=plan[len(points)];points.append(dict(value,**{k:v for k,v in target.items() if k!='code'}))
                    if target['time_index']==len(times)-1:
                        fits.append(dict(phase_index=target['phase_index'],requested_angle_deg=target['requested_angle_deg'],**rabi.fit(points[-len(times):])))
                    checkpoint();self.publish(points=list(points),fits=list(fits),phase='측정 중')
                def build(parameters,hd):
                    return rabi.build_program(dict(parameters,pulse_clocks=plan[len(points)]['pulse_clocks']),hd)
                self.call(DeviceAPI(self.worker,group=self.group)._submit('PHASE_RABI_ACQUIRE',lambda w:
                    acquisition.run(w.raw_device.controller,c,[p['code'] for p in plan],Cancellation(),received,point,builder=build)))
        except Exception as exc:error=exc
        if self.handle.cancelled() and error is None:error=OperationCancelled('Phase Rabi cancelled')
        report.update(status='cancelled' if isinstance(error,OperationCancelled) else 'failed' if error else 'completed',
            error=str(error) if error else '',finished_at=datetime.now().astimezone().isoformat())
        checkpoint();self.publish(phase=report['status'],error=report['error'],points=points,fits=fits)
        if error:raise error
        return report
