import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from labremote.runtime.workflow_runner import WorkflowTask, _TASK_LOCK
from labremote.runtime.characterization_guard import join_completed
from labremote.runtime.errors import OperationCancelled
from labremote.api.devices import DeviceAPI
from labremote.data_paths import tab_data_directory
from . import config


class PhaseShifterRunner(WorkflowTask):
    def __init__(self, worker):
        super().__init__(worker, 'PHASE_SHIFTER_RAMSEY')
        self.exclusive_fpga = True

    def start(self, settings, directory=None, single=False):
        join_completed((self.worker,))
        c = config.validate(settings, single=single)
        skipped = []
        plan = [config.resolve(c['phase_angle_deg'], c.get('calibration'))] if single else config.scan_points(c, skipped)
        with _TASK_LOCK:
            if (self.worker.waveform_runner.running() or self.worker.has_requests() or
                    any(task.running() for task in self.worker._background_tasks)):
                raise RuntimeError('다른 FPGA 작업이 끝난 뒤 실행하세요.')
            return self.launch(self._execute, (self.worker,),
                dict(settings=c, directory=str(tab_data_directory(directory, 'phase_shifter')),
                     scan_points=plan, skipped_angles=skipped, codes=[point['code'] for point in plan]))

    def _execute(self):
        from labremote.devices.fpga.adapter import Cancellation
        from .acquisition import run
        c = self.settings['settings']
        folder = Path(self.settings['directory']) / (
            datetime.now().strftime('%Y%m%d_%H%M%S') + '_phase_' + self.handle.request_id[:8])
        folder.mkdir(parents=True, exist_ok=False)
        source = folder/'source'
        source.mkdir()
        for path in Path(__file__).parent.glob('*.py'):
            shutil.copyfile(path, source/path.name)
        shutil.copyfile(config.hd.__file__, source/'hardware_definition.py')
        points = []
        report = dict(schema_version=2, settings=c, codes=self.settings['codes'],
                      scan_points=self.settings['scan_points'], points=points,
                      phase_conversion='Nominal linear: 4096 codes per 360 degrees; nearest code; 360 wraps to 0',
                      status='running', error='', folder=str(folder),
                      started_at=datetime.now().astimezone().isoformat(),
                      outputs={name: config.hd.output_mapping[name] for name in
                               [*c['outputs'].values(), *c['phase_outputs']]})

        report['skipped_angles'] = self.settings.get('skipped_angles', [])
        if c.get('calibration'):
            report['phase_conversion'] = 'Conditional empirical Ramsey inverse table; applied_angle_deg is model estimate, not measured RF phase'
            (source/'calibration.csv').write_text(c['calibration']['csv'], encoding='utf-8')

        def checkpoint():
            temporary = folder/'result.tmp'
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(folder/'result.json')

        checkpoint()
        self.publish(phase='측정 중', points=[], total=len(self.settings['codes']), folder=str(folder))
        error = None
        try:
            with (folder/'raw_fifo.csv').open('w', newline='', encoding='utf-8') as raw:
                writer = csv.writer(raw)
                writer.writerow(['point_index', 'requested_angle_deg', 'applied_angle_deg',
                                 'requested_code', 'shot', 'phase_code', 'photons', 'tag'])
                raw.flush()

                def received(code, rows):
                    target = self.settings['scan_points'][len(points)]
                    writer.writerows([len(points), target['requested_angle_deg'],
                                      target['applied_angle_deg'], code, *row] for row in rows)
                    raw.flush()

                def point(value):
                    value = dict(value, **{key: target for key, target in
                        self.settings['scan_points'][len(points)].items() if key != 'code'},
                        point_index=len(points))
                    points.append(value)
                    checkpoint()
                    self.publish(phase='측정 중', points=points)

                self.call(DeviceAPI(self.worker, group=self.group)._submit(
                    'PHASE_SHIFTER_ACQUIRE', lambda w: run(w.raw_device.controller, c,
                    self.settings['codes'], Cancellation(), received, point)))
        except Exception as exc:
            error = exc
        if self.handle.cancelled() and error is None:
            error = OperationCancelled('Phase Ramsey cancelled')
        report.update(status='cancelled' if isinstance(error, OperationCancelled)
                      else 'failed' if error else 'completed', error=str(error) if error else '',
                      finished_at=datetime.now().astimezone().isoformat())
        checkpoint()
        self.publish(phase=report['status'], points=points, error=report['error'])
        if error:
            raise error
        return report
