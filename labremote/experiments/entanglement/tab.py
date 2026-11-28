from labremote.configuration.paths import PROJECT_ROOT
from labremote.ui.responsive import FlowLayout
from labremote.devices.fpga.mapping import settings_path
from labremote.devices.fpga.mapping import bound_methods
from pathlib import Path
from PyQt5 import QtCore, QtWidgets
from labremote.api.devices import device_api
from labremote.data_paths import tab_data_directory
from labremote.experiments.entanglement import config
from labremote.experiments.entanglement.plotting import EntanglementPlot, Accumulator


@bound_methods('entanglement', editor=True)
class EntanglementTab(QtWidgets.QWidget):
    config_module=config
    experiment='entanglement'
    mapping_experiment='entanglement'
    title='RE with flip mirror'
    settings_tags={}
    workflow_path=PROJECT_ROOT/'labremote/workflow/queue_entanglement.py'
    mapping_note='Hardware: 이 FPGA의 실험 신호 매핑을 사용합니다.\nDecay: PMTA/PMTC + SYNC. State readout: PMTFA/PMTFC.\nBright = counts > threshold; 1=bright, 0=dark.\nStop: CCD EC=1/EA=0; MW OFF; AOMA/C/B/M ON; 7G ON; 2G OFF.'

    def __init__(self,worker,parent=None):
        super().__init__(parent); self.worker=worker; self.host=parent; self.api=device_api(worker)
        self.fields={}; self.plot=None; self.run_id=None; self.revision=-1
        root=QtWidgets.QVBoxLayout(self)
        note=QtWidgets.QLabel(self.title+' · 1 completed FPGA execution = 1 batch · MW source is configured by an external workflow/manual control. This tab sends no RF-generator commands.'); note.setWordWrap(True); root.addWidget(note)
        split=QtWidgets.QSplitter(); root.addWidget(split,1)
        scroll=QtWidgets.QScrollArea(); scroll.setWidgetResizable(True); scroll.setMinimumWidth(355); split.addWidget(scroll)
        self.settings_panel=QtWidgets.QWidget(); scroll.setWidget(self.settings_panel); form=QtWidgets.QFormLayout(self.settings_panel)
        self.basis=QtWidgets.QComboBox(); self.basis.addItem('ZZ basis','zz'); self.basis.addItem('MW detuned','mw_detuned'); form.addRow('Measurement basis',self.basis)
        for key,label,lo,hi,decimals in self.config_module.FIELDS:
            box=QtWidgets.QDoubleSpinBox() if decimals else QtWidgets.QSpinBox()
            if decimals:box.setDecimals(decimals)
            box.setRange(lo,hi); box.setKeyboardTracking(False)
            if key.startswith('pi_'):box.setSingleStep(.02)
            elif key=='mirror_wait_ms':box.setSingleStep(.5)
            elif key.endswith('_us'):box.setSingleStep(.01)
            form.addRow(label,box); self.fields[key]=box
        self.trial_note=QtWidgets.QLabel(); self.trial_note.setWordWrap(True); form.addRow(self.trial_note)
        self.phase_note=QtWidgets.QLabel(); self.phase_note.setWordWrap(True); form.addRow(self.phase_note)
        for box in self.fields.values():box.valueChanged.connect(self.update_trials)
        self.basis.currentIndexChanged.connect(self.update_trials)
        from labremote.ui.experiment_mapping import MappingEditor
        self.mapping=MappingEditor(worker,self.experiment,dict(basis='zz'),parent=self);form.addRow(self.mapping)
        self.basis.currentIndexChanged.connect(lambda:self.mapping.set_settings(dict(self.mapping.apply({}),basis=self.basis.currentData())))
        mapping_note=QtWidgets.QLabel(self.mapping_note)
        mapping_note.setWordWrap(True); form.addRow(mapping_note)
        for text,fn in [('Load settings',self.load),('Save settings',self.save),('Save settings as…',self.save_as)]:
            button=QtWidgets.QPushButton(text); button.clicked.connect(fn); form.addRow(button)
        right=QtWidgets.QWidget(); split.addWidget(right); layout=QtWidgets.QVBoxLayout(right)
        row=FlowLayout(); layout.addLayout(row)
        self.run=QtWidgets.QPushButton('Run '+self.title); self.stop=QtWidgets.QPushButton('Stop now / restore outputs'); self.queue=QtWidgets.QPushButton('Add to Queue')
        for b in (self.run,self.stop,self.queue):row.addWidget(b)
        self.run.clicked.connect(self.start); self.stop.clicked.connect(getattr(self.api,"stop_"+self.experiment)); self.queue.clicked.connect(self.add_to_queue)
        row=QtWidgets.QHBoxLayout(); layout.addLayout(row)
        self.directory=QtWidgets.QLineEdit(str(tab_data_directory(None,self.experiment))); row.addWidget(self.directory,1)
        self.folder_button=QtWidgets.QPushButton('Save folder'); row.addWidget(self.folder_button); self.folder_button.clicked.connect(self.choose_folder)
        self.open_button=QtWidgets.QPushButton('Open result'); row.addWidget(self.open_button); self.open_button.clicked.connect(self.open_result)
        self.status=QtWidgets.QLabel('Idle'); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.metrics=QtWidgets.QLabel(); self.metrics.setWordWrap(True); self.metrics.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse); layout.addWidget(self.metrics)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        self.figure=Figure(figsize=(12,14)); self.canvas=FigureCanvasQTAgg(self.figure); self.canvas.setMinimumSize(750,1080)
        from labremote.experiments.entanglement.view import EntanglementView
        self.live_view=EntanglementView(self,self.figure,self.canvas,self.status.setText)
        plot_scroll=QtWidgets.QScrollArea(); plot_scroll.setWidgetResizable(True); plot_scroll.setWidget(self.canvas); layout.addWidget(plot_scroll,1); split.setSizes([390,1050])
        try:c=self.config_module.load()
        except Exception as exc:c=self.config_module.defaults(); self.status.setText(str(exc))
        self.populate(c); self.render(Accumulator(c).data(),c)
        worker.task_progress.connect(self.progress)
        self.timer=QtCore.QTimer(self); self.timer.timeout.connect(self.controls); self.timer.start(300); self.controls()
        from labremote.ui.experiment_sidebar import install_settings_toggle
        self.settings_toggle=install_settings_toggle(split,scroll)

    def update_trials(self):
        n=1
        for key in ('groups_per_loop','inner_trials','fpga_loops'):n*=self.fields[key].value()
        self.trial_note.setText(f'Maximum attempts / batch: {n:,}\nFull arrival: 120 bins / coincidence: 240 bins · 1.25 ns/bin')
        mw=self.basis.currentData()=='mw_detuned'
        for key in ('pi_ea_us','pi_ec_us','detuning_hz','phase_magnitude_deg'):self.fields[key].setEnabled(mw)
        try:
            c=self.value(); p=self.config_module.phase_values(c)
            if not mw:self.phase_note.setText('ZZ: MW pulses are skipped.'); return
            self.phase_note.setText(
                f"Analysis π/2: EA {p['half_pi_ea_us']:.2f} / EC {p['half_pi_ec_us']:.2f} µs\n"
                f"π/2 start gap (EC − EA): {p['start_gap_us']:.2f} µs\n"
                f"Relative phase change (EC − EA): {p['drive_phase_deg']:.3f}°\n"
                'Δφ = 360° × detuning × Δt_start (seconds).\n'
                'Detuning = fMW − fqubit. Input is phase magnitude; sign follows detuning. Assumes equal detuning and stable coherent MW phase; excludes path offset and finite-pulse correction.')
        except Exception as exc:self.phase_note.setText(str(exc))

    def populate(self,c):
        c=self.config_module.validate(c)
        self.mapping.set_settings(c)
        for k,b in self.fields.items():b.setValue(c[k])
        self.basis.setCurrentIndex(self.basis.findData(c['basis'])); self.update_trials()

    def value(self):
        return self.config_module.validate(self.mapping.apply(dict(schema_version=1,basis=self.basis.currentData(),**self.settings_tags,
            **{k:b.value() for k,b in self.fields.items()})))

    def load(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Load Entanglement settings',str(self.config_module.ROOT),'JSON (*.json)')
        if path:
            try:self.populate(self.config_module.load(path)); self.status.setText(path)
            except Exception as exc:self.status.setText(str(exc))

    def save(self):
        self.save_to(settings_path(self.config_module.ROOT/(self.experiment+'.json')))

    def save_to(self,path):
        try:self.config_module.save_settings(path,self.value()); self.status.setText(str(path))
        except Exception as exc:self.status.setText(str(exc))

    def save_as(self):
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Save Entanglement settings',str(settings_path(self.config_module.ROOT/(self.experiment+'.json'))),'JSON (*.json)')
        if path:self.save_to(path)

    def choose_folder(self):
        path=QtWidgets.QFileDialog.getExistingDirectory(self,'Entanglement output folder',self.directory.text())
        if path:self.directory.setText(path)

    def start(self):
        try:
            if not self.directory.text().strip():raise ValueError('Choose a save folder')
            handle=getattr(self.api,"run_"+self.experiment)(settings=self.value(),directory=self.directory.text())
            if handle.done.is_set() and handle.error:raise handle.error
            self.status.setText('Starting Entanglement')
        except Exception as exc:self.status.setText(str(exc))
        self.controls()

    def add_to_queue(self):
        try:
            queue=getattr(self.host,'queue_tab',None)
            if queue is None:raise RuntimeError('Open Entanglement within the main application to use Queue')
            if queue.still_running():raise RuntimeError('Stop Queue before adding a job')
            from labremote.runtime.workflow_queue import freeze_job
            job=freeze_job(self.workflow_path,name=self.title+' · '+self.worker.name,
                parameters=dict(fpga=self.worker.name,settings=self.value()))
            queue.jobs.append(job); queue.dirty=True; queue.refresh(len(queue.jobs)-1)
            self.status.setText('Added Entanglement settings snapshot to Queue. Queue run folder is used for results.')
        except Exception as exc:self.status.setText(str(exc))

    def controls(self):
        w=self.worker; running=getattr(w,self.experiment+"_runner").running(); busy=w.has_requests() or w.waveform_runner.running() or any(t.running() for t in w._background_tasks)
        self.run.setEnabled(w.ps is not None and not w.connection_error and not w._closing and not busy)
        self.stop.setEnabled(running); self.settings_panel.setEnabled(not running); self.open_button.setEnabled(not running)
        self.directory.setEnabled(not running); self.folder_button.setEnabled(not running)
        self.queue.setEnabled(not running and not (getattr(self.host,'queue_tab',None) and self.host.queue_tab.still_running()))

    def progress(self,label,state):
        runner=getattr(self.worker,self.experiment+"_runner")
        if label!=self.experiment.upper() or state.get('run_id')!=runner.state.get('run_id'):return
        if self.run_id!=state['run_id']:self.run_id=state['run_id']; self.plot=None; self.revision=-1
        self.status.setText(f"{state.get('phase','')} · {state.get('completed_batches',0)}/{state.get('total','?')} batches · {state.get('folder','')}"+f" · Aborted batches: {state.get('aborted_batches',0)}"+(' · '+state['error'] if state.get('error') else ''))
        data=state.get('live')
        if data is not None and len(data['batches'])!=self.revision:
            self.render(data,runner.settings['settings']); self.revision=len(data['batches'])

    def render(self,data,c):
        self.live_view.submit(data,c)
        m=data['metrics']
        def fmt(key):return '—' if m[key] is None else f'{m[key]:.5g}'
        last=data.get('latest'); latest=''
        if last:
            counts=last['state_counts']
            latest=f"\nLatest: {last['outcome']} · attempts {last['attempts']:,}"
            if counts:latest+=f" · EA {counts['ea']} / EC {counts['ec']} counts → {last['state_label']}"
            if last.get('state_counts_by_pmt'):
                latest+='\n'+' / '.join(ion.upper()+': '+str(v['PMT1'])+' + '+str(v['PMT2']) for ion,v in last['state_counts_by_pmt'].items())
        self.metrics.setText(
            f"Attempts: {data['attempts']:,} · Heralds: {data['heralds']} · Exhausted batches: {m['exhausted_batches']}\n"
            f"P(herald)/attempt={fmt('p_herald')} · p_PMTA={fmt('p_pmta')} · p_PMTC={fmt('p_pmtc')}\n"
            f"After-cutoff decay counts/attempt={fmt('decay_counts_per_attempt')} · Rate={fmt('decay_countrate')} counts/s (batch wall time)"+latest)
        self.metrics.setToolTip('Full 0..119 arrival histograms are preserved. Decay counts/rates/probabilities integrate from each channel cutoff. Only complete valid batches enter statistics. Exhausted trials enter the probability denominator. Aborted/failed batches are excluded. Batch wall time includes mirror waits, detection and communication; it is not herald waiting time.' if self.experiment=='entanglement' else 'Completed heralds only. EA/EC fluorescence is PMT1 + PMT2; thresholds and integration times are independent. CCD outputs remain unchanged. Batch wall time includes sequential readout and communication.')

    def open_result(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Open Entanglement result',self.directory.text(),'Entanglement results (results.json result.json)')
        if path:
            try:
                from labremote.experiments.entanglement.storage import load_result
                result,c,data=load_result(path)
                self.plot=None; self.render(data,c); self.status.setText(result['status']+f" · Aborted batches: {result.get('aborted_batches',0)} · "+path)
            except Exception as exc:self.status.setText(str(exc))

    def shutdown(self):
        self.timer.stop(); self.live_view.stop(); getattr(self.worker,self.experiment+"_runner").cancel()
