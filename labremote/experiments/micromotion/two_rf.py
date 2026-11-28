"""Shared Two-RF experiment for the Micromotion UI and queued workflows."""
import hashlib
import math
import time
from contextlib import nullcontext
from pathlib import Path
from datetime import datetime
import numpy as np
from labremote.api.devices import DeviceAPI, SG384API
from labremote.runtime.workflow_runner import _TASK_LOCK
from labremote.runtime.jobs import WorkflowGroup
from labremote.runtime.errors import OperationCancelled
from labremote.runtime.io import Context
from labremote.runtime.bindings import managed_parameter
from labremote.devices.dac.model import atomic_json
from labremote.devices.fpga.mapping import bound_methods, write_snapshot
from labremote.data_paths import tab_data_directory
from labremote.configuration.device_config import vpp_to_dbm, dbm_to_vpp
from labremote.experiments.micromotion.runner import MicromotionRunner
from labremote.experiments.micromotion import config, analysis
from labremote.experiments.micromotion.two_rf_analysis import intersection


# Only explicit amplitude controls; no output switching or arbitrary parameters.
RF_PATHS = {
    'sg384': {'n_power_dbm': 'N output (Vpp)', 'bnc_power_dbm': 'BNC output (Vpp)'},
}


def validate(settings):
    c = config.validate(settings, mode='scan')
    if c.get('two_rf_mode') not in ('analyze', 'apply'):
        raise ValueError('Select measurement/analysis or apply/verify mode')
    if c.get('rf_family') not in RF_PATHS or c.get('rf_path') not in RF_PATHS[c['rf_family']]:
        raise ValueError('Select the connected trap RF amplitude control')
    if not c.get('rf_name'):
        raise ValueError('Select the trap RF device')
    for key in ('rf_high', 'rf_low', 'rf_final', 'rf_settle_s', 'min_angle_deg', 'max_ci_v', 'max_visibility'):
        c[key] = float(c[key])
        if not math.isfinite(c[key]):raise ValueError(key + ' must be finite')
    if c['rf_high'] == c['rf_low']:raise ValueError('High and Low RF settings must differ')
    if c['rf_high'] < c['rf_low']:raise ValueError('High RF Vpp must exceed Low RF Vpp')
    c.setdefault('rf_final_initial', True)
    if type(c['rf_final_initial']) is not bool:raise ValueError('Invalid final RF policy')
    for key in ('rf_high','rf_low','rf_final'):vpp_to_dbm(c[key])
    if not 0 <= c['rf_settle_s'] <= 600:raise ValueError('RF settling must be 0..600 s')
    if not 0 < c['min_angle_deg'] <= 90:raise ValueError('Minimum angle must be 0..90 degrees')
    if not 0 < c['max_ci_v'] <= 20:raise ValueError('Set a positive intersection uncertainty limit')
    if not 0 < c['max_visibility'] <= 1:raise ValueError('Verification visibility limit must be 0..1')
    c['rf_unit'] = 'Vpp'
    return c


@bound_methods(None)
class TwoRFRunner(MicromotionRunner):
    def __init__(self, worker):
        super().__init__(worker)
        self.label = 'TWO_RF_COMPENSATION'
        self.rf = None

    def start(self, *, settings, dac, rf, directory=None, parent=None):
        from labremote.runtime.characterization_guard import join_completed
        c = validate(settings)
        if dac is None or dac.family != 'dac':raise ValueError('Select a connected compensation DAC')
        if rf is None or (rf.family, rf.name) != (c['rf_family'], c['rf_name']):
            raise ValueError('Trap RF source does not match settings')
        participants = (self.worker, dac, rf)
        join_completed(participants)
        with _TASK_LOCK:
            if self.running():raise RuntimeError('Two-RF compensation is already running')
            self.dac, self.rf = dac, rf
            self.session = None
            self.result = None
            self.cleanup_group = WorkflowGroup()
            return self.launch(self._execute, participants,
                dict(settings=c, directory=str(tab_data_directory(directory, 'micromotion'))), parent)

    def _parameter(self, worker):
        parameter = worker.ps
        for part in self.settings['settings']['rf_path'].split('.'):
            parameter = getattr(parameter, part)
        return managed_parameter(parameter)

    def _rf_snapshot(self):
        def snapshot(w):
            p = self._parameter(w)
            if not p.spec.readable or not p.spec.writable:raise ValueError('RF control must support snapshot and restoration')
            for key in ('rf_high', 'rf_low', 'rf_final'):
                if key=='rf_final' and self.settings['settings']['rf_final_initial']:continue
                p.spec.validate(vpp_to_dbm(self.settings['settings'][key]), request=True)
            initial = Context().acquire(p)
            if initial is None:raise ValueError('Initial RF setting is unknown; cannot restore it')
            p.spec.validate(initial, request=True)
            return dbm_to_vpp(initial)
        return self.call(DeviceAPI(self.rf, group=self.group)._submit('TWO_RF_SNAPSHOT', snapshot))

    def _rf_set(self, value, cleanup=False):
        group = self._cleanup() if cleanup else self.group
        port = self.settings['settings']['rf_path'].split('_',1)[0].upper()
        handle = SG384API(self.rf, channel=port, group=group).set_power(value, unit='Vpp')
        try:
            while not handle.done.wait(.1):
                if self.session and self.dac.control_token and time.monotonic()-self.renewed>=3:
                    self._dac_call('RF_RAMP_RENEW',lambda w:w.raw_device.renew_control(self.session['token']),cleanup=cleanup)
                    self.renewed=time.monotonic()
            return self.call(handle)
        except Exception:
            handle.request_cancel()
            try:handle.wait()
            except Exception:pass
            raise

    def _cleanup(self):
        # A failed RF restoration must not cancel the independent DAC restoration.
        group = WorkflowGroup()
        group.owner = self.group.owner
        group.owns_execution = False
        return group

    def check(self):
        # A verified commit is completed atomically with its cancellation token.
        if self.handle is not None and self.handle.done.is_set() and self.handle.error is None:return
        return super().check()

    def _dac_call(self, label, callback, cleanup=False):
        if cleanup:self.cleanup_group = self._cleanup()
        return super()._dac_call(label, callback, cleanup)

    def _recover_dac(self, worker):
        self.session['token'] = worker.raw_device.acquire_control(worker.configuration_id)
        worker.control_token = self.session['token']
        self._finish_dac(worker, restore=True)

    def _scan(self, c, stage, folder, report, checkpoint):
        scan = dict(settings=c, mode='scan', experiment='micromotion', schema_version=1,
                    status='running', points=[], valley=dict(valid=False, reason='Scan incomplete'))
        report['scans'][stage] = scan
        stage_dir = folder / stage
        stage_dir.mkdir()
        with (stage_dir/'raw_fifo.jsonl').open('w', encoding='utf-8') as raw:
            for x in config.grid(c['left']):
                for y in config.grid(c['right']):
                    self.check()
                    self._dac_call('SET', lambda w: self._voltage(w, (x, y)))
                    self._settle(c['settle_s'])
                    index = len(scan['points'])
                    def partial(data):
                        atomic_json(stage_dir/f'partial_{index:05d}.json', dict(left=float(x), right=float(y), **data))
                    point = dict(index=index, left=float(x), right=float(y), **self._point(c, raw, partial))
                    scan['points'].append(point)
                    atomic_json(stage_dir/f'point_{index:05d}.json', point)
                    checkpoint(stage + f': {len(scan["points"])} points')
        self._renew(force=True)
        scan['valley'] = analysis.fit_valley(scan['points'])
        scan['status'] = 'completed'
        atomic_json(stage_dir/'results.json', scan)
        # Both conditions start from the same compensation state; lease stays held.
        self._dac_call('BASELINE', lambda w: self._voltage(w, [self.session['baseline'][k] for k in ('L_IN','R_IN')]))
        checkpoint(stage + ': fitted')
        return scan

    def _execute(self):
        c = self.settings['settings']
        folder = Path(self.settings['directory']) / ('two_rf_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + self.handle.request_id[:8])
        folder.mkdir(parents=True)
        write_snapshot(folder)
        report = dict(schema_version=1, experiment='two_rf_compensation', settings=c,
            status='running', run_id=self.handle.request_id, folder=str(folder), scans={},
            cleanup_status='not_required', applied=False, initial_rf=None,
            metadata=dict(source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (Path(__file__), Path(analysis.__file__), Path(__file__).with_name('two_rf_analysis.py'))},
                voltage_readback='DAC last-requested state; SG384 Vpp uses the existing 50-ohm conversion',
                verification='visibility + 1.96 * visibility_se <= max_visibility'))
        self.result = report
        def checkpoint(phase):
            report['phase'] = phase
            atomic_json(folder/'results.json', report)
            self.publish(phase=phase, report=report)
        error = None
        changed_rf = False
        retain = False
        try:
            checkpoint('Preflight')
            report['initial_rf'] = self._rf_snapshot()
            self._dac_call('RESERVE', self._begin_dac)
            report['dac_initial'] = self.session['baseline']
            report['dac_configuration'] = self.session['configuration']
            for stage in ('high', 'low'):
                changed_rf = True  # A failed transport may still change the output.
                self._rf_set(c['rf_' + stage])
                checkpoint(stage + ': RF settling')
                self._settle(c['rf_settle_s'])
                self._scan(c, stage, folder, report, checkpoint)
            report['intersection'] = intersection(report['scans']['high']['valley'], report['scans']['low']['valley'],
                [[c['left'][0], c['right'][0]], [c['left'][1], c['right'][1]]],
                min_angle_deg=c['min_angle_deg'], max_ci_v=c['max_ci_v'])
            checkpoint('Intersection calculated')
            if not report['intersection']['valid']:raise ValueError(report['intersection']['reason'])
            if c['two_rf_mode'] == 'apply':
                report['final_rf_vpp'] = report['initial_rf'] if c['rf_final_initial'] else c['rf_final']
                self._rf_set(report['final_rf_vpp'])
                self._settle(c['rf_settle_s'])
                self._dac_call('CANDIDATE', lambda w: self._voltage(w, report['intersection']['candidate']))
                self._settle(c['settle_s'])
                checkpoint('Verifying candidate')
                with (folder/'verification_raw_fifo.jsonl').open('w', encoding='utf-8') as raw:
                    verification = self._point(c, raw, lambda data: atomic_json(folder/'verification_partial.json', data))
                report['verification'] = verification
                fit = verification['fit']
                upper = float(fit['visibility'] + 1.96*fit['visibility_se'])
                report['verification_upper95'] = upper
                if not math.isfinite(upper) or upper > c['max_visibility']:
                    raise ValueError('Candidate failed the configured visibility limit')
                self.check()
                retain = True
        except Exception as exc:
            error = exc
        finally:
            # Serialize the short verified commit with Stop. A Stop received
            # before commit restores; one after completion cannot undo success.
            lock = getattr(self.group.stop, 'lock', None) if retain else None
            with lock if lock is not None else nullcontext():
                retain = retain and error is None and not self.handle.cancelled()
                cleanup_errors = []
                if changed_rf and not retain:
                    try:self._rf_set(report['initial_rf'], cleanup=True)
                    except Exception as exc:cleanup_errors.append('RF restore: ' + str(exc))
                if self.session:
                    try:self._dac_call('RESTORE_RELEASE', lambda w:self._finish_dac(w, restore=not retain), cleanup=True)
                    except Exception as exc:
                        cleanup_errors.append('DAC restore/release: ' + str(exc))
                        if retain:
                            try:self._rf_set(report['initial_rf'], cleanup=True)
                            except Exception as rf_error:cleanup_errors.append('RF restore: ' + str(rf_error))
                            try:self._dac_call('RECOVER', self._recover_dac, cleanup=True)
                            except Exception as dac_error:cleanup_errors.append('DAC recovery: ' + str(dac_error))
                report['cleanup_status'] = 'failed' if cleanup_errors else 'completed'
                report['cleanup_errors'] = cleanup_errors
                report['applied'] = retain and not cleanup_errors
                if cleanup_errors:error = RuntimeError('Two-RF cleanup failed: ' + '; '.join(cleanup_errors))
                if self.handle.cancelled() and error is None:error = OperationCancelled('Two-RF compensation cancelled')
                report['status'] = 'cancelled' if isinstance(error, OperationCancelled) else 'failed' if error else 'completed'
                report['reason'] = str(error) if error else ''
                report['continue_allowed'] = error is None
                try:checkpoint(report['status'])
                except Exception as save_error:
                    if retain and not cleanup_errors:
                        try:self._rf_set(report['initial_rf'], cleanup=True)
                        except Exception as exc:cleanup_errors.append('RF restore: ' + str(exc))
                        try:self._dac_call('RECOVER', self._recover_dac, cleanup=True)
                        except Exception as exc:cleanup_errors.append('DAC recovery: ' + str(exc))
                    report.update(status='failed',applied=False,continue_allowed=False,
                        cleanup_status='failed' if cleanup_errors else 'completed',
                        reason='Result save failed: ' + str(save_error))
                    if cleanup_errors:raise RuntimeError('Two-RF cleanup failed after result save: ' + '; '.join(cleanup_errors)) from save_error
                    raise
                if retain and error is None:self.handle.finish(result=report)
        if error:raise error
        return report
