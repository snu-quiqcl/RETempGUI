"""Two-RF UI; all acquisition and application run through the shared runner."""
import json
from pathlib import Path
import numpy as np
from PyQt5 import QtWidgets as W
from labremote.devices.fpga.mapping import bound_methods
from labremote.micromotion.two_rf import RF_PATHS
from labremote.configuration.micromotion import two_rf_settings, two_rf_settings_path
from .micromotion_tab import MicromotionPage


@bound_methods(None)
class TwoRFCompensationPage(MicromotionPage):
    def __init__(self, worker, bindings, parent=None):
        super().__init__(worker, bindings, 'scan', parent)
        self.setObjectName('micromotion_two_rf')
        self.run.setText('Run Two-RF Compensation')
        self.compensation_controls.hide()
        self.candidate_label.hide()
        self.phase_options.hide()
        self.measurement.hide()
        self.stop.clicked.disconnect()
        self.stop.clicked.connect(self.api.stop_micromotion)
        self.two_fields = {}
        form = self.settings_panel.layout()
        self.mode = W.QComboBox()
        self.mode.addItem('측정·분석만 — 초기 RF/DAC 복원', 'analyze')
        self.mode.addItem('최종 DAC 인가·검증 — 합격 시 유지', 'apply')
        form.insertRow(0, 'Two-RF mode', self.mode)
        self.rf_source = W.QComboBox()
        self.rf_path = W.QComboBox()
        form.insertRow(1, 'Trap RF SG384', self.rf_source)
        form.insertRow(2, 'SG384 output port', self.rf_path)
        self.rf_source.currentIndexChanged.connect(self.source_changed)
        specs = [
            ('rf_high', 'High trap RF (Vpp)', .000001, 10, .19),
            ('rf_low', 'Low trap RF (Vpp)', .000001, 10, .1),
            ('rf_final', 'Custom final trap RF (Vpp)', .000001, 10, .19),
            ('rf_settle_s', 'RF settling (s)', 0, 600, 1.),
            ('min_angle_deg', 'Minimum valley crossing angle (deg)', .1, 90, 5.),
            ('max_ci_v', 'Maximum intersection 95% half-width (V)', .000001, 20, .002),
            ('max_visibility', 'Verification visibility upper limit (0–1)', .000001, 1, .05),
        ]
        for row, (key, label, lo, hi, default) in enumerate(specs, 3):
            box = W.QDoubleSpinBox();box.setDecimals(6);box.setRange(lo, hi);box.setValue(default)
            box.setObjectName('two_rf_' + key);box.setKeyboardTracking(False)
            self.two_fields[key] = box;form.insertRow(row, label, box)
        self.final_initial=W.QCheckBox('초기 RF 값으로 복원 후 DAC 인가·검증')
        self.final_initial.setChecked(True)
        self.final_initial.toggled.connect(lambda checked:self.two_fields['rf_final'].setEnabled(not checked))
        self.two_fields['rf_final'].setEnabled(False)
        form.insertRow(6,self.final_initial)
        note = W.QLabel(
            'SG384 · EA/EC 기본값: config/operations/micromotion/*.two_rf.json\n'
            '검증: visibility + 1.96 × SE ≤ 설정 한계. 중단·실패 시 초기 RF/DAC 복원.\n'
            '기존 SG384 Vpp ramp와 출력 제한을 적용합니다.')
        note.setWordWrap(True);form.insertRow(11, note)
        self.report = None;self.pending = None
        self.canvas.setMinimumSize(720,500)
        self.settings_toggle.settings_scroll.setMinimumWidth(430)
        self.settings_toggle.expanded_width=430
        self.settings_toggle.setChecked(True)
        self.refresh_dacs();self.refresh_sources();self.change_chamber(self.chamber.currentText());self.render();self.controls()

    def change_chamber(self,chamber):
        super().change_chamber(chamber)
        if hasattr(self,'two_fields'):
            try:
                saved=two_rf_settings(chamber)
                if 'trg_pin' in saved:self.mapping.set_settings(saved)
                self._rf_settings_error=None
                for key,box in self.two_fields.items():
                    if key in saved:box.setValue(saved[key])
                self.two_fields['rf_final'].setValue(saved.get('rf_final',saved['rf_high']))
            except (OSError,ValueError) as exc:
                self._rf_settings_error=str(exc);self.status.setText(str(exc))

    def refresh_sources(self):
        if not hasattr(self, 'rf_source'):return
        sources = {family + ':' + bridge.worker.name:bridge.worker for family, bridge in self.bindings().values() if family in RF_PATHS}
        current = self.rf_source.currentData()
        choices = list(sources)
        if choices != [self.rf_source.itemData(i) for i in range(1, self.rf_source.count())]:
            self.rf_source.blockSignals(True);self.rf_source.clear();self.rf_source.addItem('Select trap RF device', None)
            for key in choices:
                family,name=key.split(':',1)
                self.rf_source.addItem(name + ' · ' + family, key)
            index = self.rf_source.findData(current)
            self.rf_source.setCurrentIndex(max(0,index));self.rf_source.blockSignals(False)
            self.source_changed()
        self._rf_workers = sources

    def source_changed(self):
        selected = self.rf_source.currentData()
        previous = self.rf_path.currentData();self.rf_path.clear()
        self.rf_path.addItem('Select amplitude channel', None)
        if selected:
            for path, title in RF_PATHS[selected.split(':',1)[0]].items():self.rf_path.addItem(title + ' · ' + path, path)
            index = self.rf_path.findData(previous)
            if index >= 0:self.rf_path.setCurrentIndex(index)

    def value(self):
        c = super().value()
        if not hasattr(self, 'two_fields'):return c
        selected = (self.rf_source.currentData() or ':').split(':',1)
        c.update(two_rf_mode=self.mode.currentData(), rf_family=selected[0], rf_name=selected[1], rf_path=self.rf_path.currentData() or '')
        c.update(rf_final_initial=self.final_initial.isChecked(),rf_unit='Vpp')
        c.update({key:box.value() for key,box in self.two_fields.items()})
        return c

    def start(self):
        try:
            if getattr(self,'_rf_settings_error',None):raise ValueError(self._rf_settings_error)
            if not self.directory.text().strip():raise ValueError('Choose a result directory')
            c = self.value()
            handle = self.api.run_two_rf_compensation(settings=c,
                dac=self._dac_workers.get(self.dac.currentData()),
                rf=self._rf_workers.get(self.rf_source.currentData()), directory=self.directory.text())
            if handle.done.is_set() and handle.error:raise handle.error
            self.status.setText('Starting Two-RF Compensation');self.controls()
        except Exception as exc:self.status.setText(str(exc))

    def controls(self):
        if not hasattr(self, 'two_fields'):return super().controls()
        w = self.worker
        running = w.two_rf_runner.running()
        busy = w.has_requests() or any(t.running() for t in w._background_tasks)
        ready = w.ps is not None and not w.connection_error and not w._closing
        self.run.setEnabled(not getattr(self,'_rf_settings_error',None) and ready and not busy and bool(self._dac_workers) and self.rf_source.currentData() is not None)
        self.stop.setEnabled(running);self.settings_panel.setEnabled(not running)
        for widget in (self.directory,self.folder_button,self.open_button):widget.setEnabled(not running)

    def progress(self, label, state):
        if label != 'TWO_RF_COMPENSATION':return
        if state.get('run_id') != self.worker.two_rf_runner.state.get('run_id'):return
        if 'report' in state:self.pending = state['report']
        self.status.setText(state.get('error') or state.get('phase') or state.get('status',''))

    def tick(self):
        if not hasattr(self, 'two_fields'):return
        if not self.worker.two_rf_runner.running():self.refresh_dacs();self.refresh_sources()
        self.controls()
        if self.pending is not None:self.report = self.pending;self.pending = None;self.render()

    def render(self, *_):
        if not hasattr(self, 'two_fields'):return
        self.figure.clear()
        axes = self.figure.subplots(1, 3)
        r = self.report or {}
        values=[p['fit']['visibility'] for scan in r.get('scans',{}).values() for p in scan.get('points',[])]
        vmax=max(values,default=1.) or 1.
        for axis, stage, color in zip(axes[:2], ('high','low'), ('tab:red','tab:blue')):
            scan = r.get('scans',{}).get(stage,{})
            points = scan.get('points',[])
            if points:
                xs=sorted({p['left'] for p in points});ys=sorted({p['right'] for p in points})
                if min(len(xs),len(ys))>=2:
                    grid=np.full((len(ys),len(xs)),np.nan)
                    for p in points:grid[ys.index(p['right']),xs.index(p['left'])]=p['fit']['visibility']
                    artist=axis.pcolormesh(xs,ys,np.ma.masked_invalid(grid),shading='nearest',cmap='viridis',vmin=0,vmax=vmax)
                else:
                    artist=axis.scatter([p['left'] for p in points],[p['right'] for p in points],
                        c=[p['fit']['visibility'] for p in points],marker='s',cmap='viridis',vmin=0,vmax=vmax)
                self.figure.colorbar(artist, ax=axis, label='Visibility',orientation='horizontal',pad=.12,fraction=.05)
            valley = scan.get('valley',{})
            if valley.get('valid'):
                line = np.asarray(valley['line'])
                axis.plot(line[:,0], line[:,1], color=color)
                axes[2].plot(line[:,0], line[:,1], color=color, label=stage + ' RF')
            axis.set_title(stage.title() + ' RF')
        result = r.get('intersection',{})
        if 'candidate' in result:
            x,y = result['candidate'];ci = result['ci95_v']
            axes[2].errorbar(x,y,xerr=ci[0],yerr=ci[1],fmt='ko',label='Intersection ±95%')
        for axis in axes:axis.set_xlabel('L_IN (V)');axis.set_ylabel('R_IN (V)');axis.grid(alpha=.2)
        axes[2].set_title('Valley intersection')
        if axes[2].lines:axes[2].legend(fontsize=8)
        self.figure.tight_layout();self.canvas.draw_idle()
        text = result.get('reason','Awaiting both RF scans')
        if 'candidate' in result:
            text = f"L_IN {result['candidate'][0]:.6f} V / R_IN {result['candidate'][1]:.6f} V\n" + (text or 'Intersection accepted')
        if 'verification_upper95' in r:text += f"\nVerification upper visibility: {r['verification_upper95']:.5f}"
        text += '\n' + ('Final compensation retained' if r.get('applied') else 'Final compensation not retained')
        self.metrics.setText(text)

    def select_point(self, event):pass

    def save_settings(self):
        from labremote.configuration.experiment_settings import save as atomic_json
        path,_ = W.QFileDialog.getSaveFileName(self,'Save Two-RF settings',str(two_rf_settings_path(self.chamber.currentText())),'JSON (*.json)')
        if path:
            try:atomic_json(path,self.value())
            except Exception as exc:self.status.setText(str(exc))

    def load_settings(self):
        path,_ = W.QFileDialog.getOpenFileName(self,'Load Two-RF settings',str(two_rf_settings_path(self.chamber.currentText())),'JSON (*.json)')
        if not path:return
        try:
            c = json.loads(Path(path).read_text(encoding='utf-8'))
            if 'two_rf_mode' in c:
                self.populate(c);self.refresh_sources()
                self.mode.setCurrentIndex(self.mode.findData(c['two_rf_mode']))
                self.rf_source.setCurrentIndex(self.rf_source.findData(c['rf_family'] + ':' + c['rf_name']))
                self.source_changed();self.rf_path.setCurrentIndex(self.rf_path.findData(c['rf_path']))
            elif c.get('chamber') in ('EA','EC'):
                self.chamber.setCurrentText(c['chamber'])
            for key,box in self.two_fields.items():
                if key in c:box.setValue(c[key])
            self.final_initial.setChecked(c.get('rf_final_initial',True))
            self._rf_settings_error=None
        except Exception as exc:self.status.setText(str(exc))

    def open_result(self):
        path,_ = W.QFileDialog.getOpenFileName(self,'Open Two-RF result',self.directory.text(),'Results (results.json)')
        if path:
            try:
                r = json.loads(Path(path).read_text(encoding='utf-8'))
                if r.get('experiment') != 'two_rf_compensation':raise ValueError('Not a Two-RF result')
                self.report = r;self.render();self.status.setText(r['status'] + ' · ' + path)
            except Exception as exc:self.status.setText(str(exc))

    def shutdown(self):
        self.timer.stop();self.worker.two_rf_runner.cancel()
