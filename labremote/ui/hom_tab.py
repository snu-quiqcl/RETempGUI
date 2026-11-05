from pathlib import Path
from PyQt5 import QtCore, QtWidgets
from labremote.api.devices import device_api
from labremote.data_paths import tab_data_directory
from labremote.hom import config
from labremote.hom.plotting import HOMPlot, Accumulator


class HOMTab(QtWidgets.QWidget):
    def __init__(self,worker,parent=None):
        super().__init__(parent); self.worker=worker; self.host=parent; self.api=device_api(worker)
        self.fields={}; self.inputs={}; self.outputs={}; self.plot=None; self.run_id=None; self.revision=-1
        root=QtWidgets.QVBoxLayout(self)
        note=QtWidgets.QLabel('HOM · All received coincidence bins · Δt = PMTC - PMTA · 1.25 ns/bin · Probabilities normalized to valid SYNC trials'); note.setWordWrap(True); root.addWidget(note)
        split=QtWidgets.QSplitter(); root.addWidget(split,1)
        scroll=QtWidgets.QScrollArea(); scroll.setWidgetResizable(True); scroll.setMinimumWidth(355); split.addWidget(scroll)
        self.settings_panel=QtWidgets.QWidget(); scroll.setWidget(self.settings_panel); form=QtWidgets.QFormLayout(self.settings_panel)
        for key,label,lo,hi in config.FIELDS:
            timing=key in config.TIMES
            box=QtWidgets.QDoubleSpinBox() if timing or key=='timeout_s' else QtWidgets.QSpinBox()
            if isinstance(box,QtWidgets.QDoubleSpinBox):box.setDecimals(2)
            factor=config.CLOCK_US if timing else 1
            box.setRange(lo*factor,hi*factor); box.setKeyboardTracking(False)
            if timing:box.setSingleStep(.01); box.setToolTip('0.01 µs = one sequencer clock; includes original instruction budget.')
            form.addRow(label,box); self.fields[key]=box
        self.trial_note=QtWidgets.QLabel(); self.trial_note.setWordWrap(True); form.addRow(self.trial_note)
        for key in ('run_number','inner_loop_number','outer_loop_in_fpga'):
            self.fields[key].valueChanged.connect(self.update_trials)
        for role in ('PMTA','PMTC','SYNC'):
            box=QtWidgets.QComboBox(); box.addItems(config.INPUTS); form.addRow(role+' input',box); self.inputs[role]=box
        self.aomb=QtWidgets.QCheckBox('Control AOMB'); form.addRow(self.aomb)
        for role in ('AOMA','AOMC','TRIG','AOMB'):
            box=QtWidgets.QComboBox()
            box.addItems([name for name,(_,port,_) in config.OUTPUTS.items() if role=='AOMB' or port==config.hd.external_control_port])
            self.outputs[role]=box; form.addRow(role+' output',box)
        mapping_note=QtWidgets.QLabel('Pin definitions: vendor/HardwareDefinition_remote_ent_test_ec.py (restart after editing)')
        mapping_note.setWordWrap(True); form.addRow(mapping_note)
        for text,fn in [('Load settings',self.load),('Save settings',self.save),('Save settings as…',self.save_as)]:
            button=QtWidgets.QPushButton(text); button.clicked.connect(fn); form.addRow(button)
        right=QtWidgets.QWidget(); split.addWidget(right); layout=QtWidgets.QVBoxLayout(right)
        row=QtWidgets.QHBoxLayout(); layout.addLayout(row)
        self.run=QtWidgets.QPushButton('Run HOM'); self.stop=QtWidgets.QPushButton('Stop / save partial'); self.queue=QtWidgets.QPushButton('Add to Queue')
        for b in (self.run,self.stop,self.queue):row.addWidget(b)
        self.run.clicked.connect(self.start); self.stop.clicked.connect(self.api.stop_hom); self.queue.clicked.connect(self.add_to_queue)
        row=QtWidgets.QHBoxLayout(); layout.addLayout(row)
        self.directory=QtWidgets.QLineEdit(str(tab_data_directory(None,'hom'))); row.addWidget(self.directory,1)
        self.folder_button=QtWidgets.QPushButton('Save folder'); row.addWidget(self.folder_button); self.folder_button.clicked.connect(self.choose_folder)
        self.open_button=QtWidgets.QPushButton('Open result'); row.addWidget(self.open_button); self.open_button.clicked.connect(self.open_result)
        self.status=QtWidgets.QLabel('Idle'); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.metrics=QtWidgets.QLabel(); self.metrics.setWordWrap(True); self.metrics.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse); layout.addWidget(self.metrics)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        self.figure=Figure(figsize=(12,10)); self.canvas=FigureCanvasQTAgg(self.figure); self.canvas.setMinimumSize(750,760)
        plot_scroll=QtWidgets.QScrollArea(); plot_scroll.setWidgetResizable(True); plot_scroll.setWidget(self.canvas); layout.addWidget(plot_scroll,1); split.setSizes([390,1050])
        try:c=config.load()
        except Exception as exc:c=config.defaults(); self.status.setText(str(exc))
        self.populate(c); self.render(Accumulator(c).data(),c)
        worker.task_progress.connect(self.progress)
        self.timer=QtCore.QTimer(self); self.timer.timeout.connect(self.controls); self.timer.start(300); self.controls()

    def update_trials(self):
        n=1
        for key in ('run_number','inner_loop_number','outer_loop_in_fpga'):n*=self.fields[key].value()
        self.trial_note.setText(f'Configured trials / batch: {n:,}')

    def populate(self,c):
        c=config.validate(c)
        for k,b in self.fields.items():b.setValue(c[k]*(config.CLOCK_US if k in config.TIMES else 1))
        for k,b in self.inputs.items():b.setCurrentText(c['inputs'][k])
        for k,box in self.outputs.items():box.setCurrentText(c['outputs'][k])
        self.aomb.setChecked(c['aomb_enabled']); self.update_trials()

    def value(self):
        return config.validate(dict(schema_version=2,aomb_enabled=self.aomb.isChecked(),inputs={k:b.currentText() for k,b in self.inputs.items()},
            outputs={k:box.currentText() for k,box in self.outputs.items()},**{k:config.from_display(k,b.value()) for k,b in self.fields.items()}))

    def load(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Load HOM settings',str(config.ROOT),'JSON (*.json)')
        if path:
            try:self.populate(config.load(path)); self.status.setText(path)
            except Exception as exc:self.status.setText(str(exc))

    def save(self):
        self.save_to(config.ROOT/'hom.local.json')

    def save_to(self,path):
        try:config.save(path,self.value()); self.status.setText(str(path))
        except Exception as exc:self.status.setText(str(exc))

    def save_as(self):
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Save HOM settings',str(config.ROOT/'hom.local.json'),'JSON (*.json)')
        if path:self.save_to(path)

    def choose_folder(self):
        path=QtWidgets.QFileDialog.getExistingDirectory(self,'HOM output folder',self.directory.text())
        if path:self.directory.setText(path)

    def start(self):
        try:
            if not self.directory.text().strip():raise ValueError('Choose a save folder')
            handle=self.api.run_hom(settings=self.value(),directory=self.directory.text())
            if handle.done.is_set() and handle.error:raise handle.error
            self.status.setText('Starting HOM')
        except Exception as exc:self.status.setText(str(exc))
        self.controls()

    def add_to_queue(self):
        try:
            queue=getattr(self.host,'queue_tab',None)
            if queue is None:raise RuntimeError('Open HOM within the main application to use Queue')
            if queue.still_running():raise RuntimeError('Stop Queue before adding a job')
            from labremote.runtime.workflow_queue import freeze_job
            job=freeze_job(Path(__file__).resolve().parents[1]/'workflow/queue_hom.py',name='HOM · '+self.worker.name,
                parameters=dict(fpga=self.worker.name,settings=self.value()))
            queue.jobs.append(job); queue.dirty=True; queue.refresh(len(queue.jobs)-1)
            self.status.setText('Added HOM settings snapshot to Queue. Queue run folder is used for results.')
        except Exception as exc:self.status.setText(str(exc))

    def controls(self):
        w=self.worker; running=w.hom_runner.running(); busy=w.has_requests() or w.waveform_runner.running() or any(t.running() for t in w._background_tasks)
        self.run.setEnabled(w.ps is not None and not w.connection_error and not w._closing and not busy)
        self.stop.setEnabled(running); self.settings_panel.setEnabled(not running); self.open_button.setEnabled(not running)
        self.directory.setEnabled(not running); self.folder_button.setEnabled(not running)
        self.queue.setEnabled(not running and not (getattr(self.host,'queue_tab',None) and self.host.queue_tab.still_running()))

    def progress(self,label,state):
        runner=self.worker.hom_runner
        if label!='HOM' or state.get('run_id')!=runner.state.get('run_id'):return
        if self.run_id!=state['run_id']:self.run_id=state['run_id']; self.plot=None; self.revision=-1
        self.status.setText(f"{state.get('phase','')} · {state.get('completed_batches',0)}/{state.get('total','?')} batches · {state.get('folder','')}"+(' · '+state['error'] if state.get('error') else ''))
        data=state.get('live')
        if data is not None and len(data['batches'])!=self.revision:
            self.render(data,runner.settings['settings']); self.revision=len(data['batches'])

    def render(self,data,c):
        if self.plot is None:self.plot=HOMPlot(self.figure,c)
        self.plot.update(data); self.canvas.draw_idle()
        m=dict(data['metrics'])
        pr=m.get('p_reference'); ph=m.get('p_hom')
        m['total_visibility']=1-ph/pr if pr and ph is not None else None
        def fmt(k):return '—' if m[k] is None else f'{m[k]:.5g}'
        last=data.get('latest'); latest='' if last is None else f" · Latest A/C/total: {sum(last['a']):,} / {sum(last['c']):,} / {sum(last['a'])+sum(last['c']):,}"
        self.metrics.setText(f"SYNC-confirmed trials: {data['trials']:,} · Trials without SYNC: {data['missing_sync']:,}"+latest+'\n'+
            f"p_PMTA={fmt('p_pmta')} · p_PMTC={fmt('p_pmtc')} · Total decay counts/trial={fmt('p_decay_total')}\n"+
            f"P(HOM)={fmt('p_hom')} · P(reference)={fmt('p_reference')} · Total visibility="+('—' if m['total_visibility'] is None else f"{100*m['total_visibility']:.2f}%"))
        self.metrics.setToolTip('Trials are not photon counts. SYNC-confirmed trials include attempts with no PMT detection. Trials without SYNC have no SYNC stopwatch completion flag. Total visibility = 1 - P(HOM)/P(reference), integrated over all received delay bins.')

    def open_result(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Open HOM result',self.directory.text(),'HOM results (results.json result.json)')
        if path:
            try:
                from labremote.hom.storage import load_result
                result,c,data=load_result(path)
                self.plot=None; self.render(data,c); self.status.setText(result['status']+' · '+path)
            except Exception as exc:self.status.setText(str(exc))

    def shutdown(self):
        self.timer.stop(); self.worker.hom_runner.cancel()
