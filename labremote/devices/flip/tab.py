from types import SimpleNamespace
from PyQt5 import QtCore, QtWidgets
from labremote.api.devices import DeviceAPI
from labremote.runtime.io import Context
from labremote.operation.flip.control import move
from .worker import FlipWorker
from .settings import NAMES, load_settings, save_endpoint
from .routing import FlipRouting


class FlipTab(QtWidgets.QWidget):
    log_message=QtCore.pyqtSignal(str)

    def __init__(self,oven,endpoint,parent=None):
        super().__init__(parent)
        self.oven,self.endpoint=oven,endpoint
        self.workers={name:FlipWorker() for name in NAMES}
        self.routing=FlipRouting(self.workers,oven)
        self._closing=False
        layout=QtWidgets.QVBoxLayout(self)
        self.host=QtWidgets.QLineEdit();self.host.setPlaceholderText('Linux flipper server host')
        self.port=QtWidgets.QSpinBox();self.port.setRange(1,65535);self.port.setValue(5556)
        self.selected=QtWidgets.QComboBox();self.selected.addItems(NAMES)
        error=''
        try:
            config=load_settings();self.host.setText(config['host']);self.port.setValue(config['port'])
        except Exception as exc:error=str(exc)
        form=QtWidgets.QFormLayout();form.addRow('Flipper server',self.host);form.addRow('Port',self.port)
        form.addRow('선택한 flipper',self.selected);layout.addLayout(form)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        self.connect_button=QtWidgets.QPushButton('선택 장비 연결')
        self.disconnect_button=QtWidgets.QPushButton('선택 장비 연결 해제')
        self.read_button=QtWidgets.QPushButton('현재 위치 읽기')
        for b in (self.connect_button,self.disconnect_button,self.read_button):row.addWidget(b)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        self.pos1=QtWidgets.QPushButton('Position 1');self.pos2=QtWidgets.QPushButton('Position 2')
        row.addWidget(self.pos1);row.addWidget(self.pos2)
        self.table=QtWidgets.QTableWidget(5,2);self.table.setHorizontalHeaderLabels(['장비','현재 위치 / 연결 상태'])
        self.table.setFixedHeight(210)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        for i,name in enumerate(NAMES):
            self.table.setItem(i,0,QtWidgets.QTableWidgetItem(name));self.table.setItem(i,1,QtWidgets.QTableWidgetItem('Disconnected'))
        layout.addWidget(self.table)
        box=QtWidgets.QGroupBox('EC shutter · oven_relays / shutter_2');sh=QtWidgets.QHBoxLayout(box)
        self.shutter_connect=QtWidgets.QPushButton('셔터 연결');self.shutter_read=QtWidgets.QPushButton('상태 읽기')
        self.shutter_open=QtWidgets.QPushButton('OPEN');self.shutter_close=QtWidgets.QPushButton('CLOSE')
        self.shutter_state=QtWidgets.QLabel('—')
        for w in (self.shutter_connect,self.shutter_read,self.shutter_open,self.shutter_close,self.shutter_state):sh.addWidget(w)
        layout.addWidget(box)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        self.ea=QtWidgets.QPushButton('EA 경로 적용');self.ec=QtWidgets.QPushButton('EC 경로 적용')
        row.addWidget(self.ea);row.addWidget(self.ec)
        self.state=QtWidgets.QLabel(error or 'EA/EC 매핑 미설정: 자동 이동 기본 OFF. 위치 1/2의 광로 의미는 현장에서 확인하세요.')
        self.state.setWordWrap(True);layout.addWidget(self.state);layout.addStretch()
        self.connect_button.clicked.connect(self._connect)
        self.disconnect_button.clicked.connect(lambda:self._selected_action('DISCONNECT'))
        self.read_button.clicked.connect(lambda:self._selected_action('READ'))
        self.pos1.clicked.connect(lambda:self._selected_action('MOVE',1))
        self.pos2.clicked.connect(lambda:self._selected_action('MOVE',2))
        self.shutter_connect.clicked.connect(self._connect_shutter)
        self.shutter_read.clicked.connect(lambda:self._shutter(None))
        self.shutter_open.clicked.connect(lambda:self._shutter('OPEN'))
        self.shutter_close.clicked.connect(lambda:self._shutter('CLOSED'))
        self.ea.clicked.connect(lambda:self._route('EA'));self.ec.clicked.connect(lambda:self._route('EC'))
        for name,worker in self.workers.items():
            worker.failure.connect(lambda action,message,n=name:self._failure(n+' '+action,message))
            worker.handle_changed.connect(lambda h,n=name:self._result(n,h))
            worker.start()
        oven.relays.handle_changed.connect(self._shutter_result)
        self.timer=QtCore.QTimer(self);self.timer.setInterval(150);self.timer.timeout.connect(self._tick);self.timer.start()
        self._tick()

    def _guard(self):
        if self._closing or self.oven.task.running() or self.routing.task.running():
            raise RuntimeError('Oven/route workflow is active; manual control is locked')

    def _failure(self,action,message):
        self.state.setText(action+': '+message);self.log_message.emit(action+': '+message)

    def _connect(self):
        try:
            self._guard()
            if not self.host.text().strip():raise ValueError('Enter Linux flipper server host')
            save_endpoint(self.host.text().strip(),self.port.value())
            DeviceAPI(self.workers[self.selected.currentText()]).connect(self.host.text().strip(),self.port.value(),self.selected.currentText())
        except Exception as exc:self._failure('FLIP_CONNECT',str(exc))

    def _selected_action(self,action,position=None):
        try:
            self._guard();worker=self.workers[self.selected.currentText()]
            if action=='DISCONNECT':DeviceAPI(worker).disconnect();return
            def execute(w):
                self._guard()
                return move(w.ps,position) if action=='MOVE' else Context().acquire(w.ps.position)
            DeviceAPI(worker)._submit('FLIP_'+action,execute)
        except Exception as exc:self._failure('FLIP',str(exc))

    def _result(self,name,handle):
        if not handle.done.is_set():return
        worker=self.workers[name]
        state='오류 · 위치 미확인' if handle.error else ('Disconnected' if worker.ps is None else 'Connected · 위치 읽기 필요')
        if handle.error is None and handle.action in ('FLIP_MOVE','FLIP_READ','FLIP_ROUTE_MOVE'):
            state='이동 중 / 미확인' if handle.result==0 else 'Position '+str(handle.result)
        self.table.item(NAMES.index(name),1).setText(state)

    def _connect_shutter(self):
        try:
            self._guard()
            DeviceAPI(self.oven.relays).connect(*self.endpoint(),self.oven.relay_name.text().strip())
        except Exception as exc:self._failure('SHUTTER_CONNECT',str(exc))

    def _shutter(self,value):
        try:
            self._guard()
            def execute(w):
                self._guard();ctx=Context()
                if value is not None:ctx.assign(w.ps.shutter_2,value)
                return ctx.acquire(w.ps.shutter_2)
            DeviceAPI(self.oven.relays)._submit('FLIP_SHUTTER',execute)
        except Exception as exc:self._failure('SHUTTER',str(exc))

    def _shutter_result(self,handle):
        if handle.done.is_set() and handle.action=='FLIP_SHUTTER':
            self.shutter_state.setText('미확인' if handle.error else str(handle.result))

    def _route(self,chamber):
        try:self._guard();self.routing.task.start(chamber)
        except Exception as exc:self._failure('FLIP_ROUTE',str(exc))

    def _tick(self):
        active=self._closing or self.oven.task.running() or self.routing.task.running()
        worker=self.workers[self.selected.currentText()]
        idle=not active and not worker.has_requests()
        self.connect_button.setEnabled(idle);self.selected.setEnabled(not active)
        self.disconnect_button.setEnabled(idle and worker.ps is not None)
        for b in (self.pos1,self.pos2,self.read_button):b.setEnabled(idle and worker.ps is not None and not worker.connection_error)
        self.host.setEnabled(not active and not any(w.ps is not None or w.has_requests() for w in self.workers.values()))
        self.port.setEnabled(self.host.isEnabled())
        relay=self.oven.relays
        self.shutter_connect.setEnabled(not active and not relay.has_requests())
        for b in (self.shutter_read,self.shutter_open,self.shutter_close):b.setEnabled(not active and not relay.has_requests() and relay.ps is not None and not relay.io_fault)
        for b in (self.ea,self.ec):b.setEnabled(not active)

    def shutdown(self):
        self._closing=True;self.timer.stop();self.routing.task.cancel()
        for worker in self.workers.values():worker.shutdown()

    def still_running(self):return self.routing.task.running() or any(w.isRunning() for w in self.workers.values())

    def lifecycle_panels(self):
        return [SimpleNamespace(worker=w,shutdown=self.shutdown,still_running=self.still_running) for w in self.workers.values()]
