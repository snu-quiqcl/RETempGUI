"""EA/EC chip-trap controls. UI never opens USB or calculates DAC codes."""
from dataclasses import replace
from pathlib import Path
import time
from PyQt5 import QtCore, QtGui, QtWidgets as W
from trap_dac.configuration import load_config, DeviceConfig
from trap_dac.model import VoltageSet, example, load_preset, atomic_json, suggested_filename
from trap_dac.sequence import VoltageSequence, SequenceRow, load_sequence, save_sequence, parse_rows
from trap_dac.timing import ManualTiming, SequenceOptions
from labremote.data_paths import DATA_ROOT
from .worker import DACWorker, DACAPI


def spin(value=0,low=-20,high=20,decimals=5):
    box=W.QDoubleSpinBox();box.setDecimals(decimals);box.setRange(low,high);box.setValue(value);box.setSingleStep(.01)
    return box


class ChipTrap(W.QWidget):
    """Planar chip electrodes, not the conical bulk-trap illustration.

    Display ordering comes from the supplied map; schematic is not a mask drawing.
    """
    def __init__(self,config,owner,parent=None):
        super().__init__(parent);self.config=config;self.owner=owner;self.setMinimumWidth(190)
        self.setMinimumHeight(max(300,len(config.for_side('left'))*29+70))

    def paintEvent(self,event):
        p=QtGui.QPainter(self);p.setRenderHint(p.Antialiasing)
        p.fillRect(self.rect(),QtGui.QColor('#eef2f7'))
        w=self.width();x=w/2;top=40;bottom=self.height()-45
        p.setPen(QtGui.QColor('#344256'));p.drawText(self.rect().adjusted(0,5,0,0),QtCore.Qt.AlignTop|QtCore.Qt.AlignHCenter,self.config.device+' CHIP TRAP')
        outer={s:[e for e in self.config.for_side(s) if e.role=='outer'] for s in ('left','right')}
        n=max(len(v) for v in outer.values());pitch=(bottom-top)/max(1,n)
        centers={}
        for side,items in outer.items():
            for i,e in enumerate(items):
                field=self.owner.editors.get(e.id)
                centers[e.id]=self.mapFromGlobal(field.mapToGlobal(field.rect().center())).y() if field is not None else top+(i+.5)*pitch
        if centers:top=min(centers.values())-15;bottom=max(centers.values())+15
        for side,items in outer.items():
            for i,e in enumerate(items):
                rect=QtCore.QRectF(8 if side=='left' else x+31,centers[e.id]-13,x-39,26)
                p.setBrush(QtGui.QColor('#d6bc72'));p.setPen(QtGui.QColor('#9b8248'));p.drawRoundedRect(rect,2,2)
                p.setPen(QtGui.QColor('#25364b'));p.drawText(rect,QtCore.Qt.AlignCenter,e.label)
        for xx in (x-24,x+11):
            p.fillRect(QtCore.QRectF(xx,top,13,bottom-top),QtGui.QColor('#96afc9'))
        p.setPen(QtGui.QColor('#597592'));p.drawText(QtCore.QRectF(x-28,bottom+2,56,18),QtCore.Qt.AlignCenter,'RF  RF')
        p.setPen(QtGui.QPen(QtGui.QColor('#b1bdc9'),1,QtCore.Qt.DashLine));p.drawLine(QtCore.QPointF(x,top),QtCore.QPointF(x,bottom))
        # Match the original EC ion location between labels 15/16 and 46/45.
        y=(top+bottom)/2
        if self.config.device=='EC':
            labels=[e.label.strip() for e in outer['left']]
            if '15' in labels and '16' in labels:y=(centers[outer['left'][labels.index('15')].id]+centers[outer['left'][labels.index('16')].id])/2
        p.setPen(QtCore.Qt.NoPen);p.setBrush(QtGui.QColor('#2787db'));p.drawEllipse(QtCore.QPointF(x,y),5,5)
        p.setPen(QtGui.QColor('#596777'));p.drawText(QtCore.QRectF(0,self.height()-22,w,20),QtCore.Qt.AlignCenter,'Planar schematic · not to scale')


class DACPanel(W.QWidget):
    log_message=QtCore.pyqtSignal(str)
    def __init__(self,name,host,port,parent=None):
        super().__init__(parent);self.name=name;self.host=host;self.port=port;self.connected=False
        self.endpoint_provider=None;self.handle=None;self.last_sent=None;self._busy=False
        self.worker=DACWorker();self.worker.name=name;self.api=DACAPI(self.worker)
        self.config=load_config(Path(__file__).resolve().parents[3]/'trap_dac/configs'/('EA.example.json' if 'ea' in name.lower() else 'EC.example.json'))
        self.folder=DATA_ROOT/'dac'/self.config.device/'presets';self.sequence_folder=DATA_ROOT/'dac'/self.config.device/'sequences'
        self.manual_timing=ManualTiming();self.options=SequenceOptions()
        root=W.QVBoxLayout(self);connection=W.QHBoxLayout();root.addLayout(connection)
        self.connection_label=W.QLabel(name+' · disconnected');connection.addWidget(self.connection_label,1)
        self.connect_button=self.button(connection,'Connect',self.connect_dac)
        self.disconnect_button=self.button(connection,'Disconnect',lambda:self.watch(self.api.disconnect()))
        self.reload_button=self.button(connection,'Reload server mapping',lambda:self.watch(self.api.reload_configuration()))
        init=W.QHBoxLayout();root.addLayout(init);init.addWidget(W.QLabel('Initial output'))
        self.initial_mode=W.QComboBox();self.initial_mode.addItems(['0 V','Current draft']);init.addWidget(self.initial_mode)
        self.initialize_button=self.button(init,'Initialize DAC',self.initialize);init.addStretch()
        self.init_note=W.QLabel('Initialization interrupts existing outputs. Connect alone never initializes.');init.addWidget(self.init_note)
        body=W.QHBoxLayout();root.addLayout(body,1)
        presets=W.QGroupBox('Voltage sets');sidebar=W.QVBoxLayout(presets);body.addWidget(presets)
        presets.setMaximumWidth(245);self.presets=W.QListWidget();sidebar.addWidget(self.presets,1)
        row=W.QHBoxLayout();sidebar.addLayout(row)
        self.button(row,'Folder',self.choose_folder);self.button(row,'Refresh',self.refresh_presets)
        row=W.QHBoxLayout();sidebar.addLayout(row);self.button(row,'Load selected',self.load_selected);self.button(row,'Open',self.open_preset)
        self.preset_name=W.QLineEdit('Manual');sidebar.addWidget(W.QLabel('Preset name'));sidebar.addWidget(self.preset_name)
        self.notes=W.QPlainTextEdit();self.notes.setMaximumHeight(90);sidebar.addWidget(W.QLabel('Notes'));sidebar.addWidget(self.notes)
        self.button(sidebar,'Save draft',self.save_draft)
        right=W.QVBoxLayout();body.addLayout(right,1)
        tools=W.QHBoxLayout();right.addLayout(tools);tools.addWidget(W.QLabel('Step (V)'))
        self.step=spin(.01,.00001,40);tools.addWidget(self.step)
        self.ldac=W.QCheckBox('Next apply: Use LDAC');self.ldac.setChecked(True);tools.addWidget(self.ldac)
        self.button(tools,'Timing',self.edit_timing);self.button(tools,'Mapping',self.show_mapping)
        self.electrode_area=W.QScrollArea();self.electrode_area.setWidgetResizable(True);right.addWidget(self.electrode_area,1)
        self.inner_box=W.QGroupBox('Pinned innerDC');self.inner_layout=W.QHBoxLayout(self.inner_box);right.addWidget(self.inner_box)
        self.quick_box=W.QGroupBox('Quick controls');self.quick_layout=W.QHBoxLayout(self.quick_box);right.addWidget(self.quick_box)
        row=W.QHBoxLayout();right.addLayout(row);self.restore_button=self.button(row,'Restore last sent',self.restore_sent)
        self.sent_note=W.QLabel('Last sent is not measured voltage');row.addWidget(self.sent_note,1)
        self.apply_button=self.button(row,'Apply voltages',self.apply)
        self.status=W.QLabel('Connect to obtain the authoritative server mapping.');self.status.setWordWrap(True);root.addWidget(self.status)
        self.sequence_tab=DACSequence(self)
        self.rebuild();self.refresh_presets()
        self.restore_local_settings()
        self.worker.connected.connect(self.on_connected);self.worker.disconnected.connect(self.on_disconnected)
        self.worker.snapshot.connect(lambda data,label:self.accept_state(data))
        self.worker.task_progress.connect(self.progress)
        self.worker.failure.connect(lambda action,msg:self.report(action+': '+msg))
        self.worker.busy_changed.connect(self.busy)
        self.timer=QtCore.QTimer(self);self.timer.setInterval(250);self.timer.timeout.connect(self.tick);self.timer.start()
        self.worker.start();self.busy(False)

    def button(self,layout,text,callback):
        button=W.QPushButton(text);layout.addWidget(button)
        button.clicked.connect(lambda checked=False:self.invoke(callback));return button

    def invoke(self,callback):
        try:return callback()
        except Exception as exc:self.report(str(exc))

    def report(self,text):self.status.setText(text);self.log_message.emit(self.name+' · '+text)

    def watch(self,handle):self.handle=handle;return handle

    def tick(self):
        self.worker.ui_alive=time.monotonic()
        if self.handle and self.handle.done.is_set():
            handle=self.handle;self.handle=None
            if handle.error:self.report(str(handle.error))
            else:
                result=handle.result or {};self.report(handle.action+' completed')
                if result.get('result'):self.accept_state(result['result'])
                if handle.action=='DAC_STEP' and self.last_sent:self.set_draft(VoltageSet.from_values(self.config,self.last_sent))
            self.busy(self.worker.has_requests())

    def connect_dac(self):
        host,port=self.endpoint_provider() if self.endpoint_provider else (self.host,self.port)
        return self.watch(self.api.connect(host,port,self.name))

    def on_connected(self,info):
        self.connected=True;self.accept_state(info);self.busy(False)

    def on_disconnected(self,message):
        self.connected=False;self.connection_label.setText(self.name+' · disconnected');self.connection_label.setStyleSheet('');self.busy(False)

    def accept_state(self,info):
        if not isinstance(info,dict) or 'configuration' not in info:return
        new=DeviceConfig.from_dict(info['configuration'])
        if new!=self.config:
            old=self.config;draft=self.draft() if hasattr(self,'editors') else None
            self.config=new;self.folder=DATA_ROOT/'dac'/new.device/'presets';self.sequence_folder=DATA_ROOT/'dac'/new.device/'sequences'
            self.rebuild()
            if draft and old.wiring()==new.wiring():
                try:self.set_draft(VoltageSet.from_values(new,draft.by_id,name=draft.name,notes=draft.notes))
                except ValueError:pass
            else:self.sequence_tab.table.setRowCount(0)
            self.sequence_tab.columns();self.refresh_presets()
        self.last_sent=info.get('last_sent')
        for eid,label in self.sent_labels.items():label.setText('--' if self.last_sent is None else f'{self.last_sent[eid]:.5f}')
        self.connection_label.setText(f'{self.name} / {new.device} · '+('Ready (TX only)' if info.get('ready') else 'USB connected · initialize required' if info.get('connected') else 'USB closed'))
        self.connection_label.setStyleSheet('color: #177749' if info.get('connected') else '')
        self.sent_note.setText('Last sent, not measured · LDAC '+str(info.get('last_ldac')))
        self.busy(self.worker.has_requests())

    def busy(self,value):
        self._busy=value
        ready=self.connected and bool((self.worker.description or {}).get('ready'))
        for w in (self.apply_button,self.quick_box):w.setEnabled(ready and not value)
        self.initialize_button.setEnabled(self.connected and not value)
        self.reload_button.setEnabled(self.connected and not value)
        self.connect_button.setEnabled(not value);self.disconnect_button.setEnabled(self.connected and not value)
        self.sequence_tab.start_button.setEnabled(ready and not value)
        self.sequence_tab.stop_button.setEnabled(value)

    def rebuild(self):
        self.editors={};self.sent_labels={}
        content=W.QWidget();row=W.QHBoxLayout(content)
        for side in ('left','right'):
            if side=='right':row.addWidget(ChipTrap(self.config,self),1)
            group=W.QGroupBox(side.title()+' electrodes');grid=W.QGridLayout(group);grid.setAlignment(QtCore.Qt.AlignTop);row.addWidget(group,2)
            for c,title in enumerate(('Electrode','Draft (V)','Quick','Last sent (V)')):grid.addWidget(W.QLabel(title),0,c)
            for r,e in enumerate((e for e in self.config.for_side(side) if e.role=='outer'),1):self.add_electrode(grid,e,r)
        self.electrode_area.setWidget(content)
        for layout in (self.inner_layout,self.quick_layout):
            while layout.count():
                item=layout.takeAt(0)
                if item.widget():item.widget().deleteLater()
        for e in (e for e in self.config.electrodes if e.role=='inner'):
            box=W.QWidget();grid=W.QGridLayout(box);self.add_electrode(grid,e,0);self.inner_layout.addWidget(box)
        components=['sym','asym'] if self.config.inner_pair else []
        if self.config.device=='EC':components+=['x','y','squeeze','squeeze4']
        for component in components:
            box=W.QWidget();line=W.QHBoxLayout(box);line.setContentsMargins(0,0,0,0);line.addWidget(W.QLabel({'squeeze':'Squeeze2'}.get(component,component.title())))
            for direction in (-1,1):self.button(line,'−' if direction<0 else '+',lambda c=component,d=direction:self.quick(d,component=c)).setMaximumWidth(32)
            self.quick_layout.addWidget(box)
        self.step.valueChanged.connect(self.update_step) if not getattr(self,'_step_wired',False) else None
        self._step_wired=True;self.update_step(self.step.value())

    def add_electrode(self,grid,e,row):
        label=W.QLabel(e.label if e.role=='outer' else e.id);label.setToolTip(f'{e.id}: chip {e.chip}, channel {e.channel}')
        field=spin(e.default_voltage);self.editors[e.id]=field
        field.setObjectName('dac_voltage_'+e.id);field.lineEdit().returnPressed.connect(lambda:self.invoke(self.apply))
        sent=W.QLabel('--');self.sent_labels[e.id]=sent
        quick=W.QWidget();layout=W.QHBoxLayout(quick);layout.setContentsMargins(0,0,0,0)
        for d in (-1,1):self.button(layout,'−' if d<0 else '+',lambda eid=e.id,d=d:self.quick(d,electrode_id=eid)).setMaximumWidth(28)
        for col,w in enumerate((label,field,quick,sent)):grid.addWidget(w,row,col)

    def update_step(self,value):
        for field in self.editors.values():field.setSingleStep(value)

    def draft(self):
        for field in self.editors.values():field.interpretText()
        return VoltageSet.from_values(self.config,{eid:f.value() for eid,f in self.editors.items()},name=self.preset_name.text(),notes=self.notes.toPlainText())

    def set_draft(self,state):
        for eid,value in state.by_id.items():self.editors[eid].setValue(value)
        self.preset_name.setText(state.name);self.notes.setPlainText(state.notes)

    def initialize(self):
        values=None if self.initial_mode.currentIndex()==0 else self.draft().by_id
        self.watch(self.api.initialize(values,use_ldac=self.ldac.isChecked()))

    def apply(self):
        if self._busy:raise RuntimeError('DAC busy')
        state=self.draft();self.watch(self.api.apply(state.by_id,use_ldac=self.ldac.isChecked(),manual_timing=self.manual_timing.as_dict(),name=state.name,notes=state.notes))

    def quick(self,direction,**target):
        if self._busy:raise RuntimeError('DAC busy')
        self.watch(self.api.step(self.draft().by_id,self.step.value(),direction,use_ldac=self.ldac.isChecked(),manual_timing=self.manual_timing.as_dict(),**target))

    def restore_sent(self):
        if self.last_sent is not None:self.set_draft(replace(self.draft(),voltages=tuple(self.last_sent[e.id] for e in self.config.electrodes)))

    def refresh_presets(self):
        self.presets.clear()
        if self.folder.exists():
            for path in sorted(self.folder.glob('*.json')):self.presets.addItem(path.name)

    def choose_folder(self):
        path=W.QFileDialog.getExistingDirectory(self,'Voltage sets',str(self.folder))
        if path:self.folder=Path(path);self.refresh_presets()

    def load_selected(self):
        if self.presets.currentItem():self.set_draft(load_preset(self.folder/self.presets.currentItem().text(),self.config))

    def open_preset(self):
        path,_=W.QFileDialog.getOpenFileName(self,'Open voltage set',str(self.folder),'Voltage set (*.json)')
        if path:self.set_draft(load_preset(path,self.config))

    def save_draft(self):
        state=self.draft();self.folder.mkdir(parents=True,exist_ok=True)
        path,_=W.QFileDialog.getSaveFileName(self,'Save voltage set',str(self.folder/suggested_filename(self.config.device,state.name)),'JSON (*.json)')
        if path:atomic_json(path,state.as_dict());self.refresh_presets()

    def show_mapping(self):
        dialog=W.QDialog(self);dialog.setWindowTitle('Server-authoritative electrode mapping');dialog.resize(600,550)
        layout=W.QVBoxLayout(dialog);text=W.QPlainTextEdit();text.setReadOnly(True)
        import json
        text.setPlainText(json.dumps(self.config.as_dict(),indent=2));layout.addWidget(text)
        layout.addWidget(W.QLabel('Edit the server mapping file, then Reload server mapping. Reconnect and initialize afterwards.'))
        dialog.exec_()

    def edit_timing(self):
        dialog=W.QDialog(self);dialog.setWindowTitle('Manual transmission timing');layout=W.QFormLayout(dialog);fields={}
        for key,value in self.manual_timing.as_dict().items():
            field=spin(value,0,5000 if key=='cooldown_ms' else 1000,2);fields[key]=field;layout.addRow(key,field)
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.Ok|W.QDialogButtonBox.Cancel);layout.addRow(buttons)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        if dialog.exec_():self.manual_timing=ManualTiming.from_dict({k:v.value() for k,v in fields.items()})

    def progress(self,label,state):
        self.sequence_tab.progress.setText(f"{state['action']}: {state.get('row',0)} / {state.get('total',0)} · {state['status']} {state.get('reason','')}")
        key=(state['job_id'],state.get('row',0),state['status'],state.get('reason',''))
        if key!=getattr(self,'_progress_key',None):
            self._progress_key=key
            self.sequence_tab.log.appendPlainText(time.strftime('%H:%M:%S')+' '+self.sequence_tab.progress.text())
        if state.get('last_sent'):
            self.last_sent=state['last_sent']
            for eid,w in self.sent_labels.items():w.setText(f'{self.last_sent[eid]:.5f}')

    def settings_path(self):
        from labremote.config.paths import CONFIG_ROOT
        if not self.name.isidentifier():raise ValueError('Invalid DAC instrument name')
        return CONFIG_ROOT/'ui'/('dac_'+self.name+'.local.json')

    def restore_local_settings(self):
        import json
        path=self.settings_path()
        if not path.exists():return
        try:
            doc=json.loads(path.read_text(encoding='utf-8'))
            self.manual_timing=ManualTiming.from_dict(doc.get('manual_timing',{}))
            self.folder=Path(doc.get('preset_folder',str(self.folder)))
            self.sequence_folder=Path(doc.get('sequence_folder',str(self.sequence_folder)))
            options=SequenceOptions.from_dict(doc.get('sequence_options',{}))
            self.sequence_tab.reuse.setChecked(options.reuse_spi_config)
            self.sequence_tab.pre_ldac.setValue(options.pre_ldac_ms)
            if doc.get('sequence'):
                seq=VoltageSequence.from_dict(doc['sequence'],self.config)
                self.sequence_tab.append(seq.rows);self.sequence_tab.name.setText(seq.name);self.ldac.setChecked(seq.use_ldac)
            self.refresh_presets()
        except Exception as exc:self.report('Local DAC settings not restored: '+str(exc))

    def save_local_settings(self):
        doc=dict(manual_timing=self.manual_timing.as_dict(),preset_folder=str(self.folder),sequence_folder=str(self.sequence_folder),
            sequence_options=dict(reuse_spi_config=self.sequence_tab.reuse.isChecked(),pre_ldac_ms=self.sequence_tab.pre_ldac.value()))
        if self.sequence_tab.table.rowCount():
            try:doc['sequence']=self.sequence_tab.sequence().as_dict()
            except ValueError as exc:self.report('Invalid sequence not autosaved: '+str(exc))
        atomic_json(self.settings_path(),doc)

    def still_running(self):return self.worker.isRunning()
    def shutdown(self):
        try:self.save_local_settings()
        except Exception as exc:self.report('DAC settings save failed: '+str(exc))
        self.timer.stop();self.worker.shutdown()


class DACSequence(W.QWidget):
    def __init__(self,owner):
        super().__init__();self.owner=owner;root=W.QVBoxLayout(self)
        row=W.QHBoxLayout();root.addLayout(row);row.addWidget(W.QLabel('Sequence name'));self.name=W.QLineEdit('Transport');row.addWidget(self.name,1)
        owner.button(row,'Open sequence',self.open);owner.button(row,'Save sequence',self.save)
        row=W.QHBoxLayout();root.addLayout(row)
        for label,fn in [('Add draft',lambda:self.append([SequenceRow(owner.draft(),self.hold.value())])),('Add preset',self.add_preset),('Duplicate',self.duplicate),('Delete',self.delete),('Up',lambda:self.move(-1)),('Down',lambda:self.move(1)),('Paste rows',self.paste),('Row to draft',self.to_draft)]:owner.button(row,label,fn)
        self.table=W.QTableWidget();self.table.setSelectionBehavior(W.QAbstractItemView.SelectRows);root.addWidget(self.table,1);self.columns()
        options=W.QHBoxLayout();root.addLayout(options)
        self.ldac=W.QCheckBox('Use LDAC');self.ldac.setChecked(True);options.addWidget(self.ldac)
        self.ldac.toggled.connect(owner.ldac.setChecked);owner.ldac.toggled.connect(self.ldac.setChecked)
        self.reuse=W.QCheckBox('Reuse SPI config');self.reuse.setChecked(True);options.addWidget(self.reuse)
        self.pre_ldac=spin(1,0,1000,2);options.addWidget(W.QLabel('Before LDAC (ms)'));options.addWidget(self.pre_ldac)
        self.hold=spin(.1,0,86400,5);options.addWidget(W.QLabel('New row Hold (s)'));options.addWidget(self.hold)
        row=W.QHBoxLayout();root.addLayout(row)
        self.start_button=owner.button(row,'Start sequence',self.start)
        self.stop_button=owner.button(row,'Stop',owner.api.cancel)
        self.progress=W.QLabel('Idle');row.addWidget(self.progress,1)
        root.addWidget(W.QLabel('UI connection lost: stop after current row; retain last output. Hold is host-timed after transmission.'))
        self.log=W.QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(1000);self.log.setMaximumHeight(130);root.addWidget(self.log)

    def columns(self):
        self.table.setColumnCount(len(self.owner.config.electrodes)+1)
        self.table.setHorizontalHeaderLabels(['Hold (s)']+[e.id+' (V)' for e in self.owner.config.electrodes])
        for i in range(self.table.columnCount()):self.table.setColumnWidth(i,100)

    def get_row(self,r):
        values=[]
        for c in range(self.table.columnCount()):
            item=self.table.item(r,c)
            if item is None:raise ValueError(f'Missing cell at row {r+1}, column {c+1}')
            values.append(float(item.text()))
        return SequenceRow(VoltageSet(self.owner.config,tuple(values[1:]),name=f'Row {r+1}'),values[0]).validate()

    def sequence(self):
        self.table.clearFocus()
        return VoltageSequence(self.owner.config,tuple(self.get_row(r) for r in range(self.table.rowCount())),self.ldac.isChecked(),self.name.text()).validate()

    def append(self,rows):
        from trap_dac.sequence import MAX_ROWS
        if self.table.rowCount()+len(rows)>MAX_ROWS:raise ValueError('Too many sequence rows')
        for row in rows:
            row.validate();r=self.table.rowCount();self.table.insertRow(r)
            for c,value in enumerate((row.hold_s,*row.state.voltages)):self.table.setItem(r,c,W.QTableWidgetItem(str(value)))

    def selected(self):return sorted({i.row() for i in self.table.selectedIndexes()})
    def duplicate(self):self.append([self.get_row(r) for r in self.selected()])
    def delete(self):
        for r in reversed(self.selected()):self.table.removeRow(r)
    def move(self,delta):
        rows=self.selected()
        if not rows:return
        if min(rows)+delta<0 or max(rows)+delta>=self.table.rowCount():return
        for r in (rows if delta<0 else reversed(rows)):
            for c in range(self.table.columnCount()):
                a=self.table.takeItem(r,c);b=self.table.takeItem(r+delta,c);self.table.setItem(r,c,b);self.table.setItem(r+delta,c,a)
        self.table.clearSelection()
        selection=self.table.selectionModel()
        for r in rows:selection.select(self.table.model().index(r+delta,0),QtCore.QItemSelectionModel.Select|QtCore.QItemSelectionModel.Rows)
    def to_draft(self):
        if self.table.currentRow()>=0:self.owner.set_draft(self.get_row(self.table.currentRow()).state)
    def add_preset(self):
        path,_=W.QFileDialog.getOpenFileName(self,'Add voltage set',str(self.owner.folder),'JSON (*.json)')
        if path:self.append([SequenceRow(load_preset(path,self.owner.config),self.hold.value())])
    def paste(self):
        text,ok=W.QInputDialog.getMultiLineText(self,'Paste rows','Voltages or Hold + voltages (CSV / TSV / bracketed rows):',W.QApplication.clipboard().text())
        if ok:self.append(parse_rows(text,self.owner.config,self.hold.value()))
    def open(self):
        path,_=W.QFileDialog.getOpenFileName(self,'Open sequence',str(self.owner.sequence_folder),'Sequences (*.csv *.json)')
        if path:
            seq=load_sequence(path,self.owner.config,use_ldac=self.ldac.isChecked())
            self.table.setRowCount(0);self.append(seq.rows);self.name.setText(seq.name);self.ldac.setChecked(seq.use_ldac)
    def save(self):
        seq=self.sequence();self.owner.sequence_folder.mkdir(parents=True,exist_ok=True)
        path,_=W.QFileDialog.getSaveFileName(self,'Save sequence',str(self.owner.sequence_folder/(self.owner.config.device+'_sequence.csv')),'CSV (*.csv);;JSON (*.json)')
        if path:save_sequence(path,seq)
    def start(self):
        self.owner.watch(self.owner.api.run_sequence(self.sequence(),sequence_options=dict(reuse_spi_config=self.reuse.isChecked(),pre_ldac_ms=self.pre_ldac.value())))
