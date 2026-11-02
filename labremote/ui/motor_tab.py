"""Twelve motor rows, one InstrumentServer endpoint; common device APIs."""
from PyQt5 import QtCore,QtWidgets
from labremote.api.devices import device_api
from labremote.config.device_config import load_device_config
from labremote.runtime.parameters import LIBRARY
from labremote.devices.motors.worker import MotorWorker


class MotorRow(QtCore.QObject):
    log_message=QtCore.pyqtSignal(str)
    def __init__(self,name,tab):
        super().__init__(tab);self.name=name;self.tab=tab;self.connected=False;self._closing=False
        self.worker=MotorWorker();self.api=device_api(self.worker)
        cfg=load_device_config('motors',name);self.scale=cfg['connection'].get('um_per_server_unit',1000)
        self.target=QtWidgets.QLineEdit(cfg.get('instrument',name))
        self.position=QtWidgets.QLabel('Unknown');self.status=QtWidgets.QLabel('Disconnected')
        self.editor=QtWidgets.QDoubleSpinBox();self.editor.setDecimals(3)
        self.editor.setRange(cfg['limits']['min_position']*self.scale,cfg['limits']['max_position']*self.scale)
        self.editor.setSingleStep(1);self.buttons=[]
        self.step=QtWidgets.QDoubleSpinBox();self.step.setDecimals(3)
        self.step.setRange(.001,self.editor.maximum()-self.editor.minimum());self.step.setValue(1.)
        self.step.valueChanged.connect(self.editor.setSingleStep)
        self.target.setMinimumWidth(90);self.target.setMaximumWidth(130)
        self.target.setToolTip('Logical motor: '+name+' — server instrument name (editable while disconnected)')
        self.indicator=QtWidgets.QLabel('●');self.indicator.setFixedWidth(14)
        def cell(*widgets):
            box=QtWidgets.QWidget();layout=QtWidgets.QHBoxLayout(box);layout.setContentsMargins(0,0,0,0);layout.setSpacing(3);layout.setAlignment(QtCore.Qt.AlignLeft)
            for w in widgets:layout.addWidget(w)
            return box
        def button(title,callback):
            b=QtWidgets.QPushButton(title);b.setMinimumWidth(0);b.setFixedHeight(28)
            b.clicked.connect(lambda checked=False:callback());self.buttons.append(b);return b
        move=cell(button('−',lambda:self.api.move_relative(-self.step.value()/self.scale)),
                  button('Move',lambda:self.api.move(self.editor.value()/self.scale)),
                  button('+',lambda:self.api.move_relative(self.step.value()/self.scale)))
        more=QtWidgets.QToolButton();more.setText('⋯');more.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu=QtWidgets.QMenu(more)
        for title,callback in [('Open',self.api.open),('Close',self.api.close),('Cancel',self.api.cancel)]:
            action=menu.addAction(title);action.triggered.connect(lambda checked=False,fn=callback:fn());self.buttons.append(action)
        more.setMenu(menu);self.buttons.append(more)
        device=cell(button('Read',self.api.status),button('Home',self.api.home),button('Stop',self.api.stop),more)
        self.backlash_actual=QtWidgets.QLabel('—');self.backlash_actual.setMinimumWidth(65)
        self.backlash_editor=QtWidgets.QDoubleSpinBox();self.backlash_editor.setDecimals(3)
        travel=(cfg['limits']['max_position']-cfg['limits']['min_position'])*self.scale
        self.backlash_editor.setRange(-travel,travel);self.backlash_editor.setSingleStep(1.)
        self.backlash_editor.setToolTip('Backlash in µm; only Apply changes the controller. No automatic write on connect.')
        self.backlash_read=button('Read',self.api.read_backlash)
        self.backlash_apply=button('Apply',lambda:self.api.set_backlash(self.backlash_editor.value()/self.scale))
        for spin in (self.editor,self.step,self.backlash_editor):spin.setFixedWidth(100);spin.setKeyboardTracking(False)
        self.status.hide()
        self.widgets=[cell(self.target,self.indicator),self.position,self.editor,self.step,move,device,
                      self.backlash_actual,self.backlash_editor,self.backlash_read,self.backlash_apply]
        self.worker.connected.connect(self.on_connected);self.worker.disconnected.connect(self.on_disconnected)
        self.worker.handle_changed.connect(self.on_handle);self.worker.failure.connect(self.on_failure)
        self.worker.identity_warning.connect(self.on_identity_warning)
        self.worker.snapshot.connect(self.snapshot)
        self.timer=QtCore.QTimer(self);self.timer.setInterval(60000);self.timer.timeout.connect(self.monitor);self.timer.start()
        self.worker.start();self.controls()
    def controls(self):
        for button in self.buttons:button.setEnabled(self.connected)
        self.target.setEnabled(not self.connected and not self.worker.has_requests())
        busy=self.worker.has_requests() or any(t.running() for t in self.worker._background_tasks)
        self.backlash_read.setEnabled(self.connected and not busy)
        self.backlash_apply.setEnabled(self.connected and not busy)
        self.indicator.setStyleSheet('color: '+('#23a55a' if self.connected else '#999')+';')
        self.indicator.setToolTip(self.status.text())
        self.tab.controls()
    def on_connected(self,info):
        self.connected=True;self.status.setText('Connected');self.controls();self.api.status()
    def on_disconnected(self,message):
        self.connected=False;self.position.setText('Unknown');self.backlash_actual.setText('—');self.status.setText(message);self.controls()
    def on_handle(self,handle):
        self.controls()
        if handle.done.is_set():self.snapshot()
    def snapshot(self,*args):
        identity=self.worker._execution_device
        status=LIBRARY.read((identity,'status'));position=LIBRARY.read((identity,'position'))
        latest=position if max(position.attempted_at,position.observed_at)>max(status.attempted_at,status.observed_at) else status
        valid=self.connected and latest.quality=='valid' and latest.verification not in ('pending','failed','mismatch')
        value=latest.observed if valid else None
        if isinstance(value,dict):
            self.status.setText('Offline' if value.get('online') is False else str(value.get('status','Unknown')))
            value=value.get('position')
        self.position.setText(f'{value*self.scale:.3f}' if isinstance(value,(int,float)) and not isinstance(value,bool) else 'Unknown')
        backlash=LIBRARY.read((identity,'backlash'))
        good=self.connected and backlash.quality=='valid' and backlash.verification not in ('pending','failed','mismatch')
        v=backlash.observed if good else None
        self.backlash_actual.setText(f'{v*self.scale:.3f}' if isinstance(v,(int,float)) and not isinstance(v,bool) else '—')
        self.indicator.setToolTip(self.status.text())
    def on_identity_warning(self,message):
        self.tab.message.setText(self.name+': '+message)
        self.log_message.emit(self.name+': '+message)
        self.tab.alarm(self.name+' — USB identity warning',message)
    def on_failure(self,action,message):
        self.backlash_actual.setText('—')
        self.status.setText(action+' failed');self.position.setText('Unknown');self.tab.message.setText(self.name+': '+message)
        self.log_message.emit(self.name+': '+message)
        self.tab.alarm(self.name+' — '+action,message)
    def monitor(self):
        if self.connected:self.api.auto_monitor()
    def shutdown(self):self._closing=True;self.timer.stop();self.worker.shutdown()
    def still_running(self):return self.worker.isRunning()


class MotorTab(QtWidgets.QWidget):
    def __init__(self,parent=None,*,endpoint=None):
        super().__init__(parent);self.rows={};self.connecting=False;self.batch=None
        if endpoint is None:
            from labremote.config.settings import load_settings
            endpoint=lambda:(load_settings()['server_host'],load_settings()['server_port'])
        self.endpoint=endpoint
        root=QtWidgets.QVBoxLayout(self);line=QtWidgets.QHBoxLayout();root.addLayout(line)
        self.connect_btn=QtWidgets.QPushButton('Connect server');self.disconnect_btn=QtWidgets.QPushButton('Disconnect all');self.read_btn=QtWidgets.QPushButton('Read all positions')
        for button in (self.connect_btn,self.disconnect_btn,self.read_btn):line.addWidget(button)
        self.connect_btn.clicked.connect(self.connect_all);self.disconnect_btn.clicked.connect(self.disconnect_all);self.read_btn.clicked.connect(self.read_all)
        self.batch_buttons=[]
        for title,action in (('Open all','open'),('Close all','close'),('Home all','home'),('Stop all','stop')):
            button=QtWidgets.QPushButton(title);button.clicked.connect(lambda checked=False,a=action:self.run_all(a))
            line.addWidget(button);self.batch_buttons.append(button)
        root.addWidget(QtWidgets.QLabel('Absolute positions in µm. 12000 µm = 12 mm. Position parameters use mm on the server.'))
        scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);root.addWidget(scroll,1)
        content=QtWidgets.QWidget();scroll.setWidget(content);self.grid=QtWidgets.QGridLayout(content);self.grid.setSpacing(4);self.headings=[]
        self.message=QtWidgets.QLabel();self.message.setWordWrap(True);root.addWidget(self.message)
        self.controls()
    def add_motor(self,name):
        if name not in self.rows:
            self.rows[name]=MotorRow(name,self)
            self.rows[name].worker.task_changed.connect(self.on_batch_changed)
        self.rebuild_rows()
        return self.rows[name]
    def rebuild_rows(self):
        for row in range(self.grid.rowCount()):self.grid.setRowStretch(row,0)
        while self.grid.count():self.grid.takeAt(0)
        for label in self.headings:label.hide();label.deleteLater()
        self.headings=[]
        def heading(text,row,col,span=1):
            label=QtWidgets.QLabel(text);label.setStyleSheet('font-weight:600; padding:4px; background:#253448; color:#e1ebf5;')
            self.headings.append(label);self.grid.addWidget(label,row,col,1,span)
        for col,title in enumerate(('Motor / Instrument','Actual (µm)','Target (µm)','Step (µm)','Move','Device','Actual','Set','Read','Apply')):
            heading(title,1,col)
        heading('Backlash (µm)',0,6,4)
        groups=[('EA collection','EA_p'),('EA excitation','EA_s'),('EC collection','EC_p'),('EC excitation','EC_s')]
        ordered=[];seen=set()
        for title,prefix in groups:
            names=[prefix+axis for axis in 'xyz' if prefix+axis in self.rows]
            if names:ordered.append((title,names));seen.update(names)
        other=[n for n in self.rows if n not in seen]
        if other:ordered.append(('Other motors',other))
        row=2
        for title,names in ordered:
            heading(title,row,0,10);row+=1
            for name in names:
                for col,w in enumerate(self.rows[name].widgets):self.grid.addWidget(w,row,col)
                row+=1
        self.grid.setColumnStretch(5,1)
        self.grid.setRowStretch(row,1)

    def controls(self):
        active=any(row.connected or row.worker.has_requests() for row in self.rows.values())
        self.connect_btn.setEnabled(not active and not self.connecting)
        self.disconnect_btn.setEnabled(active);self.read_btn.setEnabled(any(row.connected for row in self.rows.values()))
        for button in self.batch_buttons:button.setEnabled(any(r.connected for r in self.rows.values()) and (button.text()=='Stop all' or not (self.batch and self.batch.running())))
    def connect_all(self):
        self.connecting=True
        host,port=self.endpoint()
        for row in self.rows.values():
            row.api.connect_motor(host.strip(),port,row.target.text().strip())
        self.connecting=False;self.controls()
    def run_all(self,action):
        if action=='stop':
            if self.batch and self.batch.running():self.batch.cancel()
            for row in self.rows.values():
                if row.connected:row.api.cancel();row.api.stop()
            return
        from labremote.runtime.workflow_runner import WorkflowTask
        rows=[r for r in self.rows.values() if r.connected]
        if not rows or (self.batch and self.batch.running()):return
        if self.batch:self.batch.join()
        task=WorkflowTask(rows[0].worker,'MOTOR_'+action.upper()+'_ALL');self.batch=task
        def execute():
            for row in rows:
                task.check()
                api=device_api(row.worker,group=task.group)
                task.call(getattr(api,action)())
        handle=task.launch(execute,[r.worker for r in rows],{'action':action})
        self.controls()
        return handle
    def on_batch_changed(self,*args):
        self.controls()
        # Task completion is published just before its thread exits.
        if self.batch and self.batch.handle.done.is_set() and self.batch.running():
            QtCore.QTimer.singleShot(50,self.on_batch_changed)
    def disconnect_all(self):
        for row in self.rows.values():
            if row.connected or row.worker.has_requests():row.api.disconnect()
    def read_all(self):
        for row in self.rows.values():
            if row.connected:row.api.status()
    def alarm(self,title,message):
        if getattr(self.window(),'_closing',False) or all(row._closing for row in self.rows.values()):return
        box=QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning,title,message,parent=self.window())
        box.setAttribute(QtCore.Qt.WA_DeleteOnClose);box.open()
