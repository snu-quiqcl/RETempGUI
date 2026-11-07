"""Micromotion UI; all hardware work goes through existing FPGA/DAC queues."""
import json
from pathlib import Path
import numpy as np
from PyQt5 import QtCore, QtWidgets as W
from labremote.api.devices import device_api
from labremote.data_paths import tab_data_directory
from labremote.micromotion import config, analysis
from labremote.micromotion.plotting import draw, phase_text


class MicromotionPage(W.QWidget):
    verification_requested=QtCore.pyqtSignal()

    def __init__(self,worker,bindings,mode,parent=None):
        super().__init__(parent)
        self.experiment_mode=mode
        self.setObjectName('micromotion_'+mode)
        self.worker=worker;self.bindings=bindings;self.api=device_api(worker)
        self.fields={};self.report=None;self.selected=None;self.candidate=None
        self.pending=None;self.plot_axes={};self.run_id=None;self.live_result=False;self._dac_workers={}
        root=W.QVBoxLayout(self)
        note=W.QLabel('Micromotion · External RF reference · Cooling/light outputs unchanged · 1.25 ns/bin')
        note.setWordWrap(True);root.addWidget(note)
        split=W.QSplitter();root.addWidget(split,1)
        scroll=W.QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumWidth(310);split.addWidget(scroll)
        self.settings_panel=W.QWidget();scroll.setWidget(self.settings_panel);form=W.QFormLayout(self.settings_panel)
        form.setRowWrapPolicy(W.QFormLayout.WrapAllRows)
        form.setFieldGrowthPolicy(W.QFormLayout.AllNonFixedFieldsGrow)
        def add_field(label,box,visible=True):
            if visible:form.addRow(label,box)
            else:box.setParent(self.settings_panel);box.hide()
        self.chamber=W.QComboBox();self.chamber.addItems(['EC','EA']);form.addRow('Chamber',self.chamber)
        self.dac=W.QComboBox();add_field('Connected DAC',self.dac,mode=='scan')
        for key,label,choices in [('trg_pin','TRG · RF reference',config.STOPWATCH_PINS),
                                  ('pmt_pin','PMT · Photon',config.STOPWATCH_PINS),
                                  ('counter_pin','RF test counter input',('',*config.COUNTER_PINS))]:
            box=W.QComboBox()
            for pin in choices:box.addItem(pin+' · '+config.PINS[pin] if pin else 'Select wired counter input',pin)
            self.fields[key]=box;add_field(label,box,(key=='counter_pin')==(mode=='input'))
        pin_note=W.QLabel('Count the external RF on a wired counter input. ja_2 has no ordinary counter.' if mode=='input' else 'TRG and PMT must be different stopwatch inputs. Cooling outputs remain unchanged.')
        pin_note.setWordWrap(True);form.addRow(pin_note)
        for key,label,lo,hi,decimals in [
            ('rf_mhz','RF frequency (MHz)',1,100,6),('events','Accepted events / batch',10,10000000,0),
            ('batches','Batches / point',1,1000,0),('periods','RF observation periods',1,20,0),
            ('timeout_s','Timeout / point (s)',1,3600,1),('gate_us','RF test gate (µs)',.1,500,2),
            ('rf_repeats','RF test repeats',1,1000,0),('settle_s','DAC settling (s)',0,60,3)]:
            box=W.QDoubleSpinBox() if decimals else W.QSpinBox();box.setRange(lo,hi)
            if decimals:box.setDecimals(decimals);box.setSingleStep(.1 if key!='rf_mhz' else .001)
            box.setKeyboardTracking(False);box.setObjectName('micromotion_'+key)
            visible=(key in ('rf_mhz','timeout_s') or key in ('gate_us','rf_repeats') and mode=='input' or
                key in ('events','batches','periods') and mode!='input' or key=='settle_s' and mode=='scan')
            add_field(label,box,visible);self.fields[key]=box
        if mode=='scan':form.addRow(W.QLabel('2D scan · L_IN × R_IN'))
        self.ranges={}
        for key,label in [('left','L_IN (V)'),('right','R_IN (V)')]:
            row=W.QWidget();layout=W.QHBoxLayout(row);layout.setContentsMargins(0,0,0,0);boxes=[]
            for name in ('Min','Max','Step'):
                box=W.QDoubleSpinBox();box.setDecimals(6);box.setRange(.000001 if name=='Step' else -20,20)
                box.setSingleStep(.001);box.setKeyboardTracking(False);box.setToolTip(name+' voltage (V)')
                box.setObjectName('micromotion_'+key+'_'+name);layout.addWidget(box);boxes.append(box)
            self.ranges[key]=boxes;add_field(label+' min/max/step',row,mode=='scan')
        self.ldac=W.QCheckBox('Simultaneous LDAC update');add_field('',self.ldac,mode=='scan')
        policy=W.QLabel('Scan completion / Stop: restore starting L_IN/R_IN. Successful Apply selected: retain candidate. DAC values are last sent, not physical readback.')
        policy.setWordWrap(True)
        if mode=='scan':form.addRow(policy)
        for text,callback in [('Load settings',self.load_settings),('Save settings',self.save_settings)]:
            b=W.QPushButton(text);b.clicked.connect(callback);form.addRow(b)
        right=W.QWidget();split.addWidget(right);layout=W.QVBoxLayout(right)
        row=W.QHBoxLayout();layout.addLayout(row)
        self.run=W.QPushButton({'input':'Check signal','correlation':'Acquire correlation','scan':'Start 2D scan'}[mode]);self.stop=W.QPushButton('Stop / save partial');row.addWidget(self.run);row.addWidget(self.stop)
        self.run.clicked.connect(self.start);self.stop.clicked.connect(self.api.stop_micromotion)
        row=W.QHBoxLayout();layout.addLayout(row)
        self.directory=W.QLineEdit(str(tab_data_directory(None,'micromotion')));row.addWidget(self.directory,1)
        self.folder_button=W.QPushButton('Save folder');self.open_button=W.QPushButton('Open result');row.addWidget(self.folder_button);row.addWidget(self.open_button)
        self.folder_button.clicked.connect(self.choose_folder);self.open_button.clicked.connect(self.open_result)
        self.status=W.QLabel('Idle · configure physical pins and voltage ranges before running');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.metrics=W.QLabel();self.metrics.setWordWrap(True);self.metrics.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse);layout.addWidget(self.metrics)
        self.phase_options=W.QWidget();options=W.QHBoxLayout(self.phase_options);options.setContentsMargins(0,0,0,0)
        self.phase_unit=W.QComboBox();self.phase_unit.addItem('Phase: degrees','deg');self.phase_unit.addItem('Phase: radians','rad')
        self.phase_unit.setObjectName('phase_unit')
        self.mask_phase=W.QCheckBox('Mask unresolved phase');self.mask_phase.setChecked(True);self.mask_phase.setObjectName('mask_phase')
        self.mask_phase.setToolTip('Visibility > 3 radial SE and phase SE < 60 deg. Raw estimates are always saved.')
        options.addWidget(self.phase_unit);options.addWidget(self.mask_phase);options.addStretch()
        layout.addWidget(self.phase_options);self.phase_options.setVisible(mode!='input')
        self.measurement=W.QLabel();self.measurement.setWordWrap(True);self.measurement.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse);layout.addWidget(self.measurement)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg,NavigationToolbar2QT
        self.figure=Figure(figsize=(12,11));self.canvas=FigureCanvasQTAgg(self.figure);self.canvas.setMinimumSize(760 if mode=='scan' else 600,950 if mode=='scan' else 480)
        layout.addWidget(NavigationToolbar2QT(self.canvas,self))
        chart_scroll=W.QScrollArea();chart_scroll.setWidgetResizable(True);chart_scroll.setWidget(self.canvas);layout.addWidget(chart_scroll,1)
        self.canvas.mpl_connect('button_press_event',self.select_point)
        self.compensation_controls=W.QWidget();row=W.QHBoxLayout(self.compensation_controls);row.setContentsMargins(0,0,0,0);layout.addWidget(self.compensation_controls)
        row.addWidget(W.QLabel('Compensation line position'))
        self.slider=W.QSlider(QtCore.Qt.Horizontal);self.slider.setRange(0,1000);row.addWidget(self.slider,1)
        self.apply=W.QPushButton('Apply selected compensation + verify');row.addWidget(self.apply)
        self.candidate_label=W.QLabel('No compensation line yet');layout.addWidget(self.candidate_label)
        self.candidate_label.setVisible(mode=='scan');self.compensation_controls.setVisible(mode=='scan')
        self.slider.valueChanged.connect(self.move_candidate);self.apply.clicked.connect(self.apply_candidate)
        self.chamber.currentTextChanged.connect(self.change_chamber)
        self.phase_unit.currentIndexChanged.connect(self.render);self.mask_phase.toggled.connect(self.render)
        try:self.populate(self.saved_settings('EC'))
        except Exception as exc:self.populate(config.defaults());self.status.setText(str(exc))
        self.report=self.empty_report();self.render()
        worker.task_progress.connect(self.progress)
        self.timer=QtCore.QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(500)
        split.setSizes([340,1000]);self.tick()

    def empty_report(self):
        return dict(settings=self.value(),mode=self.experiment_mode,points=[],valley=dict(valid=False,reason='Awaiting measurement'))

    def populate(self,c):
        c=config.validate(c)
        for key,box in self.fields.items():
            if isinstance(box,W.QComboBox):box.setCurrentIndex(box.findData(c[key]))
            else:box.setValue(c[key])
        for key,boxes in self.ranges.items():
            for box,value in zip(boxes,c[key]):box.setValue(value)
        self.ldac.setChecked(c['use_ldac'])
        self.chamber.blockSignals(True);self.chamber.setCurrentText(c['chamber']);self.chamber.blockSignals(False)

    def value(self):
        c=dict(schema_version=1,chamber=self.chamber.currentText(),use_ldac=self.ldac.isChecked(),
            **{key:box.currentData() if isinstance(box,W.QComboBox) else box.value() for key,box in self.fields.items()},
            **{key:[box.value() for box in boxes] for key,boxes in self.ranges.items()})
        return config.validate(c)

    def change_chamber(self,chamber):
        try:self.populate(self.saved_settings(chamber));self.refresh_dacs(prefer=True)
        except Exception as exc:self.status.setText(str(exc))

    def saved_settings(self,chamber):
        path=config.ROOT/(chamber+'.'+self.experiment_mode+'.local.json')
        return config.load(path,chamber=chamber) if path.exists() else config.load(chamber=chamber)

    def refresh_dacs(self,prefer=False):
        workers={key:bridge.worker for key,(family,bridge) in self.bindings().items() if family=='dac'}
        current=self.dac.currentData();keys=list(workers)
        if keys!=[self.dac.itemData(i) for i in range(self.dac.count())]:
            self.dac.clear()
            for key in keys:self.dac.addItem(key,key)
            index=self.dac.findData(current)
            if index>=0:self.dac.setCurrentIndex(index)
            else:prefer=True
        self._dac_workers=workers
        if prefer:
            for i,key in enumerate(keys):
                if self.chamber.currentText().lower() in key.lower():self.dac.setCurrentIndex(i);break

    def start(self):
        try:
            c=self.value();self.begin(c,self.experiment_mode)
        except Exception as exc:self.status.setText(str(exc))

    def begin(self,c,mode,candidate=None):
        if not self.directory.text().strip():raise ValueError('Choose a result directory')
        handle=self.api.run_micromotion(settings=c,mode=mode,
            dac=self._dac_workers.get(self.dac.currentData()),directory=self.directory.text(),candidate=candidate)
        if handle.done.is_set() and handle.error:raise handle.error
        if mode!='apply':self.live_result=True;self.selected=None;self.candidate=None
        else:self.verification_requested.emit()
        self.status.setText('Starting '+mode);self.controls()

    def apply_candidate(self):
        try:
            if not self.can_apply():raise ValueError('Complete a valid scan and select its connected DAC first')
            if self.value()!=self.report['settings']:raise ValueError('Restore the measured scan settings before applying its compensation line')
            self.begin(self.report['settings'],'apply',list(self.candidate))
        except Exception as exc:self.status.setText(str(exc))

    def can_apply(self):
        r=self.report or {};w=self._dac_workers.get(self.dac.currentData())
        return bool(self.live_result and r.get('mode')=='scan' and r.get('status')=='completed'
            and r.get('cleanup')=='restored' and r.get('valley',{}).get('apply_allowed')
            and self.candidate is not None and w and w.name==r.get('dac'))

    def controls(self):
        runner=self.worker.micromotion_runner;running=runner.running();w=self.worker
        busy=w.has_requests() or w.waveform_runner.running() or any(t.running() for t in w._background_tasks)
        connected=w.ps is not None and not w.connection_error and not w._closing
        needs_dac=self.experiment_mode=='scan'
        self.run.setEnabled(connected and not busy and (not needs_dac or bool(self._dac_workers)))
        self.stop.setEnabled(running);self.settings_panel.setEnabled(not running)
        for widget in (self.directory,self.folder_button,self.open_button):widget.setEnabled(not running)
        self.slider.setEnabled(not running and bool((self.report or {}).get('valley',{}).get('valid')))
        self.apply.setEnabled(connected and not busy and self.can_apply())

    def progress(self,label,state):
        if label!='MICROMOTION' or state.get('run_id')!=self.worker.micromotion_runner.state.get('run_id'):return
        report=state.get('report')
        report_mode=report.get('mode') if report else self.worker.micromotion_runner.settings.get('mode')
        destination='correlation' if report_mode=='apply' else report_mode
        if destination!=self.experiment_mode:return
        if self.run_id!=state['run_id']:
            self.run_id=state['run_id'];self.selected=None;self.candidate=None
            self.live_result=True
            if report_mode=='apply' and report:self.populate(report['settings'])
        if 'report' in state:self.pending=state['report']
        if state.get('error'):self.status.setText(state['error'])

    def tick(self):
        if not self.worker.micromotion_runner.running():self.refresh_dacs()
        if self.pending is not None:
            self.report=self.pending;self.pending=None
            r=self.report;v=r.get('valley',{})
            if v.get('valid') and self.candidate is None:
                baseline=r.get('dac_initial',{});voltage=[baseline.get('L_IN',v['center'][0]),baseline.get('R_IN',v['center'][1])]
                self.candidate=analysis.nearest_candidate(v,voltage)
                ends=np.array(v['line'])[[0,-1]];d=ends[1]-ends[0]
                fraction=float((np.array(self.candidate)-ends[0])@d/(d@d))
                self.slider.blockSignals(True);self.slider.setValue(round(fraction*1000));self.slider.blockSignals(False)
            elif v.get('valid') and self.candidate is not None:
                self.candidate=analysis.nearest_candidate(v,self.candidate)
            self.status.setText(f"{r.get('status','running')} · {len(r.get('points',[]))}/{r.get('planned_points','—')} points · {r.get('cleanup','')}\n{r.get('folder','')}\n{r.get('error','')} {r.get('cleanup_error','')}")
            current=r.get('current_point')
            if current:
                self.status.setText(self.status.text()+f"\nCurrent point: L_IN {current.get('left')} / R_IN {current.get('right')} V · accepted {current.get('accepted',0):,} / {r['settings']['events']*r['settings']['batches']:,}")
            self.render()
        self.controls()

    def render(self):
        if self.report is None:return
        self.plot_axes=draw(self.figure,self.report,self.selected,self.candidate,self.phase_unit.currentData(),self.mask_phase.isChecked());self.canvas.draw_idle()
        points=self.report.get('points',[])
        point=points[self.selected] if self.selected is not None and 0<=self.selected<len(points) else points[-1] if points else None
        if point and point.get('fit'):
            fit=point['fit'];where='' if point.get('left') is None else f"L_IN {point['left']:.6f} V / R_IN {point['right']:.6f} V · "
            self.measurement.setText(where+f"Visibility {fit['visibility']*100:.3f} ± {fit.get('visibility_se',0)*100:.3f}% (1 SE) · "+phase_text(fit,self.phase_unit.currentData(),self.mask_phase.isChecked()))
        else:self.measurement.clear()
        v=self.report.get('valley',{})
        if v.get('valid'):
            n=np.array(v['normal']);center=np.array(v['center']);b=float(n@center+v['offset_mv']/1000)
            equation=(f"R_IN = {-n[0]/n[1]:.6g} × L_IN + {b/n[1]:.6g} V" if abs(n[1])>1e-5 else f"L_IN = {b/n[0]:.6g} V")
            self.metrics.setText(f"{equation}\nValley floor: {100*v['floor']:.3f}% · reduced χ²: {v['reduced_chi2']:.3g} · 95% local CI\n"+'; '.join(v['warnings']))
        else:self.metrics.setText(v.get('reason',''))
        self.candidate_label.setText('No compensation line yet' if self.candidate is None else
            f'L_IN {self.candidate[0]:.6f} V / R_IN {self.candidate[1]:.6f} V · retain on successful verification; restore on failure/Stop')

    def move_candidate(self,value):
        v=(self.report or {}).get('valley',{})
        if not v.get('valid'):return
        line=np.array(v['line']);self.candidate=(line[0]+value/1000*(line[-1]-line[0])).tolist();self.render()

    def select_point(self,event):
        if event.inaxes is None or event.inaxes not in (self.plot_axes.get('map'),self.plot_axes.get('phase_map')) or event.xdata is None or event.ydata is None:return
        points=self.report.get('points',[])
        if not points:return
        c=self.report['settings'];dx=c['left'][2];dy=c['right'][2]
        distances=[((p['left']-event.xdata)/dx)**2+((p['right']-event.ydata)/dy)**2 for p in points]
        i=int(np.argmin(distances))
        if distances[i]>.55:return
        self.selected=i;self.render()

    def choose_folder(self):
        path=W.QFileDialog.getExistingDirectory(self,'Micromotion output folder',self.directory.text())
        if path:self.directory.setText(path)

    def load_settings(self):
        path,_=W.QFileDialog.getOpenFileName(self,'Micromotion settings',str(config.ROOT),'JSON (*.json)')
        if path:
            try:self.populate(config.load(path))
            except Exception as exc:self.status.setText(str(exc))

    def save_settings(self):
        try:
            c=self.value();config.save(config.ROOT/(c['chamber']+'.'+self.experiment_mode+'.local.json'),c)
            self.status.setText('Settings saved for '+c['chamber']+' / '+self.experiment_mode)
        except Exception as exc:self.status.setText(str(exc))

    def open_result(self):
        path,_=W.QFileDialog.getOpenFileName(self,'Open micromotion result',self.directory.text(),'Micromotion results (results.json)')
        if path:
            try:
                r=json.loads(Path(path).read_text(encoding='utf-8'))
                if r.get('experiment')!='micromotion' or r.get('schema_version')!=1:raise ValueError('Not a micromotion result')
                destination='correlation' if r.get('mode')=='apply' else r.get('mode')
                if destination!=self.experiment_mode:raise ValueError('Open this archive in the '+str(destination)+' tab')
                config.validate(r['settings']);self.report=r;self.live_result=False;self.candidate=None;self.selected=None
                self.render();self.status.setText(r['status']+' · '+path)
            except Exception as exc:self.status.setText(str(exc))

    def shutdown(self):
        self.timer.stop();self.worker.micromotion_runner.cancel()


class MicromotionTab(W.QTabWidget):
    """Independent pages/results with one mutually exclusive hardware runner."""
    def __init__(self,worker,bindings,parent=None):
        super().__init__(parent)
        self.worker=worker;self.experiments={}
        for mode,title in [('input','Signal'),('correlation','RF–Photon Correlation'),('scan','2D Scan')]:
            page=MicromotionPage(worker,bindings,mode,self);self.experiments[mode]=page;self.addTab(page,title)
        self.experiments['scan'].verification_requested.connect(lambda:self.setCurrentWidget(self.experiments['correlation']))

    def shutdown(self):
        for page in self.experiments.values():page.shutdown()
