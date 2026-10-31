from types import SimpleNamespace
from PyQt5 import QtCore, QtWidgets
from labremote.api.devices import DeviceAPI
from labremote.runtime.io import Context
from labremote.operation.flip.control import move
from .worker import FlipWorker, FlipDiscoveryWorker
from .settings import load_settings, save_endpoint, save_settings
from .routing import FlipRouting


class FlipTab(QtWidgets.QWidget):
    log_message=QtCore.pyqtSignal(str)

    def __init__(self,oven,endpoint,parent=None):
        super().__init__(parent)
        self.oven,self.endpoint=oven,endpoint
        self.workers={};self._rows={};self._discovering=False;self._listed_endpoint=None;self._server_names=[]
        self.routing=FlipRouting(self.workers,oven)
        self._closing=False
        layout=QtWidgets.QVBoxLayout(self)
        self.host=QtWidgets.QLineEdit();self.host.setPlaceholderText('Linux flipper server host')
        self.port=QtWidgets.QSpinBox();self.port.setRange(1,65535);self.port.setValue(5556)
        self.selected=QtWidgets.QComboBox();self.selected.setMinimumWidth(200)
        error='';config={'names':[],'routes':{}}
        try:
            config=load_settings();self.host.setText(config['host']);self.port.setValue(config['port'])
        except Exception as exc:error=str(exc)
        form=QtWidgets.QFormLayout();form.addRow('Flipper server',self.host);form.addRow('Port',self.port)
        form.addRow('선택한 flipper',self.selected);layout.addLayout(form)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        self.discover_button=QtWidgets.QPushButton('서버 flipper 목록 불러오기');row.addWidget(self.discover_button)
        self.route_settings_button=QtWidgets.QPushButton('EA / EC 경로 설정');row.addWidget(self.route_settings_button)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        self.connect_button=QtWidgets.QPushButton('선택 장비 연결')
        self.disconnect_button=QtWidgets.QPushButton('선택 장비 연결 해제')
        self.read_button=QtWidgets.QPushButton('현재 위치 읽기')
        for b in (self.connect_button,self.disconnect_button,self.read_button):row.addWidget(b)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        self.pos1=QtWidgets.QPushButton('Position 1');self.pos2=QtWidgets.QPushButton('Position 2')
        row.addWidget(self.pos1);row.addWidget(self.pos2)
        self.table=QtWidgets.QTableWidget(0,2);self.table.setHorizontalHeaderLabels(['장비','현재 위치 / 연결 상태'])
        self.table.setFixedHeight(210)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
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
        self.state=QtWidgets.QLabel(error or '서버 목록을 불러온 뒤 장비를 선택하세요. 자동 경로는 로컬 설정을 사용합니다. 포획 workflow는 현재 EC 전용입니다.')
        self.state.setWordWrap(True);layout.addWidget(self.state);layout.addStretch()
        self.discover_button.clicked.connect(self._discover)
        self.route_settings_button.clicked.connect(self._edit_routes)
        self.discoverer=FlipDiscoveryWorker(self)
        self.discoverer.devices_found.connect(self._discovered)
        self.discoverer.failure.connect(self._discovery_failed)
        self.discoverer.start()
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
        saved=set(config.get('names',[]))
        for route in config.get('routes',{}).values():saved.update(route)
        for name in sorted(saved):self._add_worker(name)
        oven.relays.handle_changed.connect(self._shutter_result)
        self.timer=QtCore.QTimer(self);self.timer.setInterval(150);self.timer.timeout.connect(self._tick);self.timer.start()
        self._tick()

    def _add_worker(self,name):
        if name in self.workers:return
        worker=FlipWorker();self.workers[name]=worker
        row=self.table.rowCount();self.table.insertRow(row);self._rows[name]=row
        self.table.setItem(row,0,QtWidgets.QTableWidgetItem(name))
        self.table.setItem(row,1,QtWidgets.QTableWidgetItem('Disconnected / 목록 확인 필요'))
        worker.failure.connect(lambda action,message,n=name:self._failure(n+' '+action,message))
        worker.handle_changed.connect(lambda h,n=name:self._result(n,h))
        worker.start()

    def _discover(self):
        try:
            self._guard()
            if self._discovering:return
            if any(w.has_requests() for w in self.workers.values()):raise RuntimeError('Wait for flipper operations to finish')
            endpoint=(self.host.text().strip(),self.port.value())
            if not endpoint[0]:raise ValueError('Enter Linux flipper server host')
            save_endpoint(*endpoint)
            self._discovering=True;self._listed_endpoint=endpoint
            self.state.setText('서버 장비 목록 조회 중…');self._tick()
            self.discoverer.scan(*endpoint)
        except Exception as exc:self._failure('FLIP_DISCOVERY',str(exc))

    def _discovered(self,descriptors):
        self._discovering=False
        if self._closing:return
        if self.oven.task.running() or self.routing.task.running():
            self._listed_endpoint=None;self.state.setText('장비 작업이 시작되어 목록 갱신을 보류했습니다. 작업 후 다시 조회하세요.');return
        previous=self.selected.currentText()
        self._server_names=sorted(d.name for d in descriptors if d.family=='thorlabs_mff' and d.name.isidentifier())
        self.routing.available_names=set(self._server_names)
        selectable=sorted(set(self._server_names)|{n for n,w in self.workers.items() if w.ps is not None})
        self.selected.clear();self.selected.addItems(selectable)
        if previous in selectable:self.selected.setCurrentText(previous)
        for name in self._server_names:self._add_worker(name)
        for name,row in self._rows.items():
            if name not in self._server_names:self.table.item(row,1).setText('현재 서버 목록에 없음')
            elif self.workers[name].ps is None:self.table.item(row,1).setText('Disconnected')
        self.state.setText(f'MFF flipper {len(self._server_names)}개 발견. 실제 서버 이름으로 연결합니다. 경로 설정은 별도로 저장하세요.')
        self._tick()

    def _discovery_failed(self,message):
        self._discovering=False;self._listed_endpoint=None;self._server_names=[];self.routing.available_names=set()
        self._failure('FLIP_DISCOVERY',message);self._tick()

    def _edit_routes(self):
        try:
            self._guard()
            if self._discovering or self._listed_endpoint!=(self.host.text().strip(),self.port.value()):
                raise RuntimeError('Load the current server flipper list first')
            config=load_settings()
            dialog=QtWidgets.QDialog(self);dialog.setWindowTitle('EA / EC flipper 경로 설정');dialog.resize(620,380)
            layout=QtWidgets.QVBoxLayout(dialog)
            note=QtWidgets.QLabel('저장은 장비를 움직이지 않습니다. Position 1/2의 실제 광로를 확인해서 지정하세요.\nEA는 수동 경로 적용용이며, 현재 이온 포획 workflow는 EC 경로만 사용합니다.')
            note.setWordWrap(True);layout.addWidget(note)
            table=QtWidgets.QTableWidget(0,3);table.setHorizontalHeaderLabels(['서버 장비 이름','EA','EC']);layout.addWidget(table)
            names=sorted(set(self._server_names)|{n for r in config['routes'].values() for n in r})
            fields={}
            for row,name in enumerate(names):
                table.insertRow(row);item=QtWidgets.QTableWidgetItem(name+(' (서버에 없음)' if name not in self._server_names else ''))
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable);table.setItem(row,0,item)
                for col,chamber in enumerate(('EA','EC'),1):
                    box=QtWidgets.QComboBox();box.addItem('이동 안 함',None);box.addItem('Position 1',1);box.addItem('Position 2',2)
                    box.setCurrentIndex(box.findData(config['routes'].get(chamber,{}).get(name)))
                    table.setCellWidget(row,col,box);fields[chamber,name]=box
            table.horizontalHeader().setStretchLastSection(True);table.resizeColumnsToContents()
            auto=QtWidgets.QCheckBox('EC 이온 포획 시작 시 저장한 flipper 경로 자동 적용');auto.setChecked(config['auto_route']);layout.addWidget(auto)
            error=QtWidgets.QLabel();error.setWordWrap(True);layout.addWidget(error)
            buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save|QtWidgets.QDialogButtonBox.Cancel);layout.addWidget(buttons)
            buttons.rejected.connect(dialog.reject)
            def save():
                try:
                    self._guard()
                    routes={ch:{n:box.currentData() for (c,n),box in fields.items() if c==ch and box.currentData() is not None} for ch in ('EA','EC')}
                    self._save_routes(routes,auto.isChecked());dialog.accept()
                except Exception as exc:error.setText(str(exc))
            buttons.accepted.connect(save);dialog.exec_()
        except Exception as exc:self._failure('FLIP_SETTINGS',str(exc))

    def _save_routes(self,routes,automatic):
        self._guard()
        endpoint=(self.host.text().strip(),self.port.value())
        if self._discovering or self._listed_endpoint!=endpoint:raise RuntimeError('Reload the current server list')
        missing={n for route in routes.values() for n in route}-set(self._server_names)
        if missing:raise ValueError('Remove missing flippers from routes: '+', '.join(sorted(missing)))
        if automatic and not routes.get('EC'):raise ValueError('Choose at least one EC flipper before enabling automatic routing')
        config=load_settings();config.update(host=endpoint[0],port=endpoint[1],names=self._server_names,routes=routes,auto_route=automatic)
        save_settings(config)
        self.state.setText('EA/EC 경로 저장 완료 · 자동 EC 경로 '+('ON' if automatic else 'OFF')+' · 장비는 이동하지 않았습니다.')

    def _guard(self):
        if self._closing or self.oven.task.running() or self.routing.task.running():
            raise RuntimeError('Oven/route workflow is active; manual control is locked')

    def _failure(self,action,message):
        self.state.setText(action+': '+message);self.log_message.emit(action+': '+message)

    def _connect(self):
        try:
            self._guard()
            if not self.host.text().strip():raise ValueError('Enter Linux flipper server host')
            if self._discovering or self._listed_endpoint!=(self.host.text().strip(),self.port.value()) or self.selected.currentText() not in self._server_names:
                raise RuntimeError('Load the current server list and select a flipper first')
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
        self.table.item(self._rows[name],1).setText(state)

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
        worker=self.workers.get(self.selected.currentText())
        idle=not active and not self._discovering and worker is not None and not worker.has_requests()
        self.connect_button.setEnabled(idle and self.selected.currentText() in self._server_names and self._listed_endpoint==(self.host.text().strip(),self.port.value()));self.selected.setEnabled(not active and not self._discovering)
        self.disconnect_button.setEnabled(idle and worker is not None and worker.ps is not None)
        for b in (self.pos1,self.pos2,self.read_button):b.setEnabled(idle and self.selected.currentText() in self._server_names and worker is not None and worker.ps is not None and not worker.connection_error)
        self.host.setEnabled(not active and not self._discovering and not any(w.ps is not None or w.has_requests() for w in self.workers.values()))
        self.port.setEnabled(self.host.isEnabled())
        self.discover_button.setEnabled(not active and not self._discovering and not any(w.has_requests() for w in self.workers.values()))
        self.route_settings_button.setEnabled(not active and not self._discovering and self._listed_endpoint==(self.host.text().strip(),self.port.value()))
        relay=self.oven.relays
        self.shutter_connect.setEnabled(not active and not relay.has_requests())
        for b in (self.shutter_read,self.shutter_open,self.shutter_close):b.setEnabled(not active and not relay.has_requests() and relay.ps is not None and not relay.io_fault)
        for b in (self.ea,self.ec):b.setEnabled(not active)

    def shutdown(self):
        self._closing=True;self.timer.stop();self.routing.task.cancel();self.discoverer.shutdown()
        for worker in self.workers.values():worker.shutdown()

    def still_running(self):return self.discoverer.isRunning() or self.routing.task.running() or any(w.isRunning() for w in self.workers.values())

    def lifecycle_panels(self):
        return [SimpleNamespace(worker=w,shutdown=self.shutdown,still_running=self.still_running) for w in (self.discoverer,*self.workers.values())]
