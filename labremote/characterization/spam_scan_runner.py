"""A two-dimensional outer loop around the unchanged SPAM PulseRunner."""
import csv
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from labremote.api.devices import device_api
from labremote.devices.fpga.mapping import bound_methods, write_snapshot
from labremote.data_paths import characterization_directory
from labremote.runtime.workflow_runner import WorkflowTask, _TASK_LOCK
from labremote.runtime.jobs import WorkflowGroup
from labremote.runtime.errors import OperationCancelled
from .pulse_runner import PulseRunner
from . import config, spam_scan as model


@bound_methods('spam')
class SpamScanRunner(WorkflowTask):
    def __init__(self, worker):
        super().__init__(worker, 'SPAM_2D_SCAN')
        self.exclusive_fpga = True
        self.exclusive_device_controls = True
        # Separate instance preserves the standalone SPAM tab's result/state.
        self.point_runner = PulseRunner(worker, 'spam')
        self.point_runner.label = 'SPAM_2D_POINT'
        self.results = {}

    def start(self, settings, workers, *, directory=None, parent=None):
        if self.handle is not None and self.handle.done.is_set():
            self.join()
        c = model.validate(settings)
        resolved = {}
        for key in ('x', 'y'):
            axis = c[key]
            if axis['family'] == 'spam':
                continue
            worker = workers.get((axis['family'], axis['device']))
            if worker is None:
                raise ValueError('축 장비를 찾을 수 없습니다: ' + axis['device'])
            self.validate_device(axis)
            resolved[key] = worker
        participants = tuple(dict.fromkeys([self.worker, *resolved.values()]))
        from labremote.runtime.characterization_guard import join_completed
        join_completed(participants)
        with _TASK_LOCK, ExitStack() as locks:
            for worker in sorted(set(resolved.values()), key=id):
                locks.enter_context(worker._lock)
            if self.running():
                raise RuntimeError('SPAM 2D Scan is already running')
            for worker in participants:
                if worker.has_foreground_requests() or any(t.running() for t in worker._background_tasks):
                    raise RuntimeError('장비 작업 종료 후 시작하세요: ' + worker.name)
            self.axis_workers = resolved
            request = dict(settings=c, directory=str(characterization_directory(directory, c['spam']['chamber'], 'spam_2d')))
            handle = self.launch(self._execute, participants, request, parent)
            if not (handle.done.is_set() and handle.error):
                for worker in resolved.values():
                    worker._spam_scan_owner = self.group.owner
            return handle

    def _run(self, callback, handle):
        try:
            super()._run(callback, handle)
        finally:
            for worker in self.axis_workers.values():
                with worker._lock:
                    if getattr(worker, '_spam_scan_owner', None) is self.group.owner:
                        worker._spam_scan_owner = None

    def validate_device(self, axis):
        from labremote.runtime.parameters import registry
        from labremote.config.device_config import load_rf_device_config, optional_number, sg_power_cap_dbm
        p = model.spec(axis)
        policy = registry().get(axis['family'], model.path(axis))
        for v in model.axis_values(axis):
            policy.validate(v * p.scale if p.decimals else v, request=True)
        if axis['parameter'] == 'power':
            cfg = load_rf_device_config(axis['family'], axis['device'])
            cap = (optional_number(cfg, 'channels', axis['channel'], 'limits', 'max_power_dbm')
                   if axis['family'] == 'windfreak' else sg_power_cap_dbm(cfg, axis['channel']))
            if cap is not None and axis['stop'] > cap:
                raise ValueError(f"{axis['device']} power exceeds configured limit {cap} dBm")

    def axis_api(self, key, group=None):
        axis = self.settings['settings'][key]
        return device_api(self.axis_workers[key], channel=axis['channel'], group=group or self.group)

    def apply_axis(self, key, value, group=None, native=False):
        p = model.spec(self.settings['settings'][key])
        api = self.axis_api(key, group)
        target = value if native else value * p.scale
        if p.decimals == 0:
            target = int(target)
        return self.call(getattr(api, p.method)(target))

    def _execute(self):
        c = self.settings['settings']
        chamber = c['spam']['chamber']
        # Keep nested PulseRunner paths below Windows' usual path limit.
        # The complete UUID remains in configuration/result metadata.
        folder = Path(self.settings['directory']) / (datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + self.handle.request_id[:8])
        folder.mkdir(parents=True, exist_ok=False)
        write_snapshot(folder)
        config.save(folder / 'configuration.json', dict(**self.settings, fpga=self.worker.name, run_id=self.handle.request_id))
        xs, ys = model.axis_values(c['x']), model.axis_values(c['y'])
        points, initial, touched, restoration = [], {}, set(), {}
        report = dict(experiment='spam_2d', chamber=chamber, folder=str(folder), run_id=self.handle.request_id,
                      expected_points=len(xs)*len(ys), completed_points=0, status='running', error='')
        self.publish(chamber=chamber, phase='Starting', folder=str(folder), total=len(xs)*len(ys), points=0,
                     settings=c, records=[])
        error = None
        try:
            # Acquire every restore value before the first write. DDS values
            # are last-transmitted settings, not measured optical power.
            if c['restore']:
                for key in self.axis_workers:
                    value = self.call(self.axis_api(key).acquire(model.path(c[key])))
                    model.number(value, 'Initial ' + key)
                    from labremote.runtime.parameters import registry
                    registry().get(c[key]['family'], model.path(c[key])).validate(value, request=True)
                    initial[key] = value
            config.save(folder / 'initial_values.json', initial)
            for iy, y in enumerate(ys):
                for ix, x in enumerate(xs):
                    self.check()
                    point = dict(ix=ix, iy=iy, x=x, y=y, status='running', metrics={}, folder=None, error='')
                    self.publish(phase=f'Setting ({ix+1}, {iy+1})', current=[ix, iy])
                    try:
                        # Reapply both axes for an unambiguous point, including
                        # two parameters on the same physical instrument.
                        for key, value in (('y', y), ('x', x)):
                            if key in self.axis_workers:
                                touched.add(key)  # failed writes may have changed hardware
                                self.apply_axis(key, value)
                                self.wait(c[key]['settle_s'])
                        settings = model.settings_at(c, x, y)
                        handle = self.point_runner.start(chamber, settings=settings,
                            directory=folder / f'p{iy:03d}_{ix:03d}', parent=self.group)
                        try:
                            result = self.call(handle)
                        finally:
                            self.point_runner.join()
                        data = self.point_runner.results[chamber]['data']
                        point.update(status='completed', folder=str(Path(result['folder']).relative_to(folder)), metrics=model.metrics(data))
                    except Exception as exc:
                        point.update(status='cancelled' if isinstance(exc, OperationCancelled) else 'failed', error=str(exc))
                        child = self.point_runner.results.get(chamber, {})
                        child_folder = child.get('report', {}).get('folder')
                        if child_folder and Path(child_folder).is_relative_to(folder / f'p{iy:03d}_{ix:03d}'):
                            point['folder'] = str(Path(child_folder).relative_to(folder))
                        raise
                    finally:
                        points.append(point)
                        config.save(folder / 'points.json', points)
                        self.publish(records=points, points=sum(p['status']=='completed' for p in points), phase='Measuring')
        except Exception as exc:
            error = exc
        finally:
            self.publish(phase='Restoring / saving')
            # A fresh cancellation token permits cleanup after Stop; preserve
            # the original execution owner so the reserved FPGA stays owned.
            for key in reversed(tuple(self.axis_workers)):
                if key not in touched or not c['restore']:
                    continue
                cleanup = WorkflowGroup()
                cleanup.owner = self.group.owner
                cleanup.owns_execution = False
                try:
                    self.apply_axis(key, initial[key], group=cleanup, native=True)
                    restoration[key] = 'restored'
                except Exception as exc:
                    restoration[key] = 'failed: ' + str(exc)
                    error = error or RuntimeError('장비 초기값 복원 실패: ' + str(exc))
            if self.handle.cancelled() and error is None:
                error = OperationCancelled('SPAM 2D Scan cancelled')
            report.update(status='cancelled' if isinstance(error, OperationCancelled) else 'failed' if error else 'completed',
                          error=str(error) if error else '', completed_points=sum(p['status']=='completed' for p in points),
                          restoration=restoration, restore_requested=c['restore'])
            config.save(folder / 'points.json', points)
            config.save(folder / 'result.json', report)
            with (folder / 'summary.csv').open('w', newline='', encoding='utf-8-sig') as stream:
                columns = ['ix', 'iy', 'x', 'y', 'status', *model.METRICS, 'folder', 'error']
                writer = csv.DictWriter(stream, columns)
                writer.writeheader()
                for p in points:
                    writer.writerow({**{k:v for k,v in p.items() if k != 'metrics'}, **p['metrics']})
            try:
                from matplotlib.figure import Figure
                from matplotlib.backends.backend_agg import FigureCanvasAgg
                figure = Figure(figsize=(9, 6)); FigureCanvasAgg(figure)
                model.draw_map(figure, c, points)
                figure.savefig(folder / 'heatmap.png', dpi=140)
            except Exception as exc:
                # Raw/point records are already durable even if plotting fails.
                report['plot_error'] = str(exc)
                config.save(folder / 'result.json', report)
            self.results[chamber] = dict(report=report, settings=c, records=points)
            self.publish(phase=report['status'], result=report, records=points, error=report['error'])
        if error is not None:
            raise error
        return report
