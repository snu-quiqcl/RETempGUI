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
        row=tab.grid.rowCount()
        for col,widget in enumerate((QtWidgets.QLabel(name),self.target,self.position,self.editor,self.step,self.status)):tab.grid.addWidget(widget,row,col)
        for col,(title,action) in enumerate((('Read',lambda:self.api.status()),('Move',lambda:self.api.move(self.editor.value()/self.scale)),('Open',self.api.open),('Home',self.api.home),('Stop',self.api.stop),('Close',self.api.close),('Cancel',self.api.cancel),('−',lambda:self.api.move_relative(-self.step.value()/self.scale)),('+',lambda:self.api.move_relative(self.step.value()/self.scale))),6):
            button=QtWidgets.QPushButton(title);button.clicked.connect(lambda checked=False,fn=action:fn());tab.grid.addWidget(button,row,col);self.buttons.append(button)
        self.worker.connected.connect(self.on_connected);self.worker.disconnected.connect(self.on_disconnected)
        self.worker.handle_changed.connect(self.on_handle);self.worker.failure.connect(self.on_failure)
        self.worker.identity_warning.connect(self.on_identity_warning)
        self.worker.snapshot.connect(self.snapshot)
        self.timer=QtCore.QTimer(self);self.timer.setInterval(60000);self.timer.timeout.connect(self.monitor);self.timer.start()
        self.worker.start();self.controls()
    def controls(self):
        for button in self.buttons:button.setEnabled(self.connected)
        self.target.setEnabled(not self.connected and not self.worker.has_requests())
        self.tab.controls()
    def on_connected(self,info):
        self.connected=True;self.status.setText('Connected');self.controls();self.api.status()
    def on_disconnected(self,message):
        self.connected=False;self.position.setText('Unknown');self.status.setText(message);self.controls()
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
    def on_identity_warning(self,message):
        self.tab.message.setText(self.name+': '+message)
        self.log_message.emit(self.name+': '+message)
        self.tab.alarm(self.name+' — USB identity warning',message)
    def on_failure(self,action,message):
        self.status.setText(action+' failed');self.position.setText('Unknown');self.tab.message.setText(self.name+': '+message)
        self.log_message.emit(self.name+': '+message)
        self.tab.alarm(self.name+' — '+action,message)
    def monitor(self):
        if self.connected:self.api.monitor()
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
        for title,action in (('Open all','open'),('Close all','close'),('Home all','home')):
            button=QtWidgets.QPushButton(title);button.clicked.connect(lambda checked=False,a=action:self.run_all(a))
            line.addWidget(button);self.batch_buttons.append(button)
        root.addWidget(QtWidgets.QLabel('Absolute positions in µm. 12000 µm = 12 mm. Position parameters use mm on the server.'))
        self.grid=QtWidgets.QGridLayout();root.addLayout(self.grid)
        for col,title in enumerate(('Motor','Instrument','Actual (µm)','Target (µm)','Step (µm)','Status')):self.grid.addWidget(QtWidgets.QLabel(title),0,col)
        self.message=QtWidgets.QLabel();self.message.setWordWrap(True);root.addWidget(self.message);root.addStretch()
        self.controls()
    def add_motor(self,name):
        if name not in self.rows:
            self.rows[name]=MotorRow(name,self)
            self.rows[name].worker.task_changed.connect(self.on_batch_changed)
        return self.rows[name]
    def controls(self):
        active=any(row.connected or row.worker.has_requests() for row in self.rows.values())
        self.connect_btn.setEnabled(not active and not self.connecting)
        self.disconnect_btn.setEnabled(active);self.read_btn.setEnabled(any(row.connected for row in self.rows.values()))
        for button in self.batch_buttons:button.setEnabled(any(r.connected for r in self.rows.values()) and not (self.batch and self.batch.running()))
    def connect_all(self):
        self.connecting=True
        host,port=self.endpoint()
        for row in self.rows.values():
            row.api.connect_motor(host.strip(),port,row.target.text().strip())
        self.connecting=False;self.controls()
    def run_all(self,action):
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
