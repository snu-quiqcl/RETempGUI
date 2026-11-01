from types import SimpleNamespace
from collections import deque
from PyQt5 import QtCore, QtWidgets, QtGui
from .display import load_display
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
        self._current_endpoint=self.endpoint()
        self.workers={};self._rows={};self._discovering=False;self._listed_endpoint=None;self._server_names=[]
        self.routing=FlipRouting(self.workers,oven,endpoint=lambda:self._current_endpoint)
        self._closing=False
        self.cards={};self._bulk_queue=deque();self._bulk_handle=None;self._bulk_endpoint=None;self._bulk_failed=[];self._bulk_active=False
        layout=QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel('메인 InstrumentServer의 서버 주소와 포트를 사용합니다.'))
        self._request_endpoint=None
        self.selected=QtWidgets.QComboBox();self.selected.setMinimumWidth(200)
        error='';config={'names':[],'routes':{}}
        try:
            config=load_settings()
        except Exception as exc:error=str(exc)
        # Keep the selection API for existing programmatic callers; controls are per device.
        self.selected.setParent(self);self.selected.hide()
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        self.discover_button=QtWidgets.QPushButton('서버 flipper 목록 불러오기');row.addWidget(self.discover_button)
        self.connect_all_button=QtWidgets.QPushButton('Flipper 전체 연결');row.addWidget(self.connect_all_button)
        self.connect_all_button.clicked.connect(self._connect_all)
        self.display_reload=QtWidgets.QPushButton('별명 / 이미지 새로고침');row.addWidget(self.display_reload)
        self.display_reload.clicked.connect(self._reload_display)
        self.display_config={}
        try:self.display_config=load_display()
        except Exception as exc:error=str(exc)
        self.cards_scroll=QtWidgets.QScrollArea();self.cards_scroll.setWidgetResizable(True)
        cards_widget=QtWidgets.QWidget();self.cards_layout=QtWidgets.QVBoxLayout(cards_widget)
        self.cards_layout.setAlignment(QtCore.Qt.AlignTop)
        self.cards_scroll.setWidget(cards_widget);layout.addWidget(self.cards_scroll,1)
        self.empty_label=QtWidgets.QLabel('서버 flipper 목록을 불러오면 장비별 버튼이 표시됩니다.');self.cards_layout.addWidget(self.empty_label)
        # Legacy entry points remain callable; no table or shared move buttons are displayed.
        self.route_settings_button=QtWidgets.QPushButton(self)
        self.connect_button=QtWidgets.QPushButton(self);self.disconnect_button=QtWidgets.QPushButton(self)
        self.read_button=QtWidgets.QPushButton(self);self.pos1=QtWidgets.QPushButton(self);self.pos2=QtWidgets.QPushButton(self)
        for button in (self.route_settings_button,self.connect_button,self.disconnect_button,self.read_button,self.pos1,self.pos2):button.hide()
        box=QtWidgets.QGroupBox('EC shutter · oven_relays / shutter_2');sh=QtWidgets.QHBoxLayout(box)
        self.shutter_connect=QtWidgets.QPushButton('셔터 연결');self.shutter_read=QtWidgets.QPushButton('상태 읽기')
        self.shutter_open=QtWidgets.QPushButton('OPEN');self.shutter_close=QtWidgets.QPushButton('CLOSE')
        self.shutter_state=QtWidgets.QLabel('—')
        for w in (self.shutter_connect,self.shutter_read,self.shutter_open,self.shutter_close,self.shutter_state):sh.addWidget(w)
        layout.addWidget(box)
        self.ea=QtWidgets.QPushButton(self);self.ec=QtWidgets.QPushButton(self)
        self.ea.hide();self.ec.hide()
        self.state=QtWidgets.QLabel(error or '서버 목록을 불러온 뒤 장비를 선택하세요. 자동 경로는 로컬 설정을 사용합니다. 포획 workflow는 현재 EC 전용입니다.')
        self.state.setWordWrap(True);layout.addWidget(self.state)
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
        box=QtWidgets.QGroupBox(name);row=QtWidgets.QGridLayout(box)
        status=QtWidgets.QLabel('Disconnected / 목록 확인 필요');status.setWordWrap(True);row.addWidget(status,0,0,1,2)
        buttons={};toolbar=QtWidgets.QHBoxLayout();row.addLayout(toolbar,1,0,1,2)
        for key,title in (('connect','연결'),('disconnect','연결 해제'),('read','위치 읽기')):
            button=QtWidgets.QPushButton(title);toolbar.addWidget(button);buttons[key]=button
        aliases={};images={}
        for col,position in enumerate((1,2)):
            key='pos'+str(position);button=QtWidgets.QPushButton('Position '+str(position))
            button.setMinimumHeight(58)
            font=button.font();font.setPointSize(max(12,font.pointSize()+2));font.setBold(True);button.setFont(font)
            row.addWidget(button,2,col);buttons[key]=button
            label=QtWidgets.QLabel();label.setAlignment(QtCore.Qt.AlignCenter);label.setWordWrap(True)
            label.setTextFormat(QtCore.Qt.PlainText);row.addWidget(label,3,col);aliases[position]=label
            image=QtWidgets.QLabel();image.setAlignment(QtCore.Qt.AlignCenter)
            image.setFixedHeight(110);row.addWidget(image,4,col);images[position]=image
            row.setColumnStretch(col,1)
        buttons['connect'].clicked.connect(lambda _,n=name:self._connect_named(n))
        buttons['disconnect'].clicked.connect(lambda _,n=name:self._named_action(n,'DISCONNECT'))
        buttons['read'].clicked.connect(lambda _,n=name:self._named_action(n,'READ'))
        buttons['pos1'].clicked.connect(lambda _,n=name:self._named_action(n,'MOVE',1))
        buttons['pos2'].clicked.connect(lambda _,n=name:self._named_action(n,'MOVE',2))
        self.cards[name]=dict(box=box,status=status,buttons=buttons,aliases=aliases,images=images,error='')
        self._apply_display(name)
        self.cards_layout.addWidget(box);self.empty_label.hide()
        worker.failure.connect(lambda action,message,n=name:self._failure(n+' '+action,message))
        worker.handle_changed.connect(lambda h,n=name:self._result(n,h))
        worker.start()

    def _apply_display(self, name):
        card=self.cards[name]
        for position in (1,2):
            cfg=self.display_config.get(name,{}).get(str(position),{})
            card['aliases'][position].setText(cfg.get('label') or '방향 이름 미설정')
            image=card['images'][position];image.clear();image.hide()
            path=cfg.get('image')
            if path:
                # Decode a bounded thumbnail; no camera or instrument I/O.
                reader=QtGui.QImageReader(path);reader.setAutoTransform(True)
                size=reader.size()
                if size.isValid():reader.setScaledSize(size.scaled(240,100,QtCore.Qt.KeepAspectRatio))
                pixels=reader.read()
                if pixels.isNull():
                    image.setText('이미지를 읽을 수 없습니다');image.setToolTip(path)
                else:
                    image.setPixmap(QtGui.QPixmap.fromImage(pixels).scaled(240,100,QtCore.Qt.KeepAspectRatio,QtCore.Qt.SmoothTransformation))
                    image.setToolTip(path)
                image.show()

    def _reload_display(self):
        try:
            config=load_display()
            self.display_config=config
            for name in self.cards:self._apply_display(name)
            self.state.setText('별명 / 이미지 갱신 완료 · 장비 이동 없음')
        except Exception as exc:self._failure('FLIP_DISPLAY',str(exc))

    def _discover(self):
        try:
            self._guard()
            if self._discovering:return
            if any(w.has_requests() for w in self.workers.values()):raise RuntimeError('Wait for flipper operations to finish')
            endpoint=self.endpoint()
            if not endpoint[0]:raise ValueError('Enter the main InstrumentServer host')
            save_endpoint(*endpoint)
            self._discovering=True;self._request_endpoint=endpoint;self._listed_endpoint=endpoint
            self.state.setText('서버 장비 목록 조회 중…');self._tick()
            self.discoverer.scan(*endpoint)
        except Exception as exc:self._failure('FLIP_DISCOVERY',str(exc))

    def _discovered(self,descriptors):
        self._discovering=False
        if self._closing:return
        if self._request_endpoint!=self.endpoint():
            self.invalidate_server_list();self.state.setText('메인 서버가 변경되었습니다. 목록을 다시 조회하세요.');return
        if self.oven.task.running() or self.routing.task.running():
            self._listed_endpoint=None;self.state.setText('장비 작업이 시작되어 목록 갱신을 보류했습니다. 작업 후 다시 조회하세요.');return
        previous=self.selected.currentText()
        self._server_names=sorted(d.name for d in descriptors if d.family=='thorlabs_mff' and d.name.isidentifier())
        self.routing.available_names=set(self._server_names)
        selectable=sorted(set(self._server_names)|{n for n,w in self.workers.items() if w.ps is not None})
        self.selected.clear();self.selected.addItems(selectable)
        if previous in selectable:self.selected.setCurrentText(previous)
        for name in self._server_names:self._add_worker(name)
        for name,card in self.cards.items():
            if name not in self._server_names:card['status'].setText('현재 서버 목록에 없음')
            elif self.workers[name].ps is None:card['status'].setText('Disconnected')
        self.state.setText(f'MFF flipper {len(self._server_names)}개 발견. 전체 연결 또는 장비별 연결 버튼을 누르세요.')
        self._tick()

    def invalidate_server_list(self,*args):
        self._current_endpoint=self.endpoint()
        self._listed_endpoint=None;self._server_names=[];self.routing.available_names=set()
        self._bulk_queue.clear()
        self._tick()

    def accept_server_devices(self,endpoint,descriptors):
        # The main Rescan button can populate this tab without another request.
        if self._closing or self._discovering or endpoint!=self.endpoint():return
        if self.oven.task.running() or self.routing.task.running():return
        try:save_endpoint(*endpoint)
        except Exception as exc:self._failure('FLIP_SETTINGS',str(exc));return
        self._request_endpoint=self._listed_endpoint=endpoint
        self._discovered(descriptors)

    def _discovery_failed(self,message):
        self._discovering=False;self._listed_endpoint=None;self._server_names=[];self.routing.available_names=set()
        self._failure('FLIP_DISCOVERY',message);self._tick()

    def _edit_routes(self):
        try:
            self._guard()
            if self._discovering or self._listed_endpoint!=self.endpoint():
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
        endpoint=self.endpoint()
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

    def _connected_name(self,name):
        w=self.workers.get(name)
        active=getattr(w,'_active',None)
        if active is not None and active.action=='CONNECT' and not active.done.is_set():return False
        return w is not None and w.ps is not None and not w.connection_error and w._execution_device==(*self.endpoint(),name)

    def _connect_named(self,name):
        try:
            self._guard()
            if not self.endpoint()[0]:raise ValueError('Enter the main InstrumentServer host')
            if self._discovering or self._listed_endpoint!=self.endpoint() or name not in self._server_names:
                raise RuntimeError('Load the current server flipper list first')
            worker=self.workers[name]
            if worker.has_requests():raise RuntimeError('Wait for this flipper operation to finish')
            save_endpoint(*self.endpoint())
            self.cards[name]['error']='';self.cards[name]['status'].setText('연결 중…')
            return DeviceAPI(worker).connect(*self.endpoint(),name)
        except Exception as exc:
            if name in self.cards:self.cards[name]['error']=str(exc);self.cards[name]['status'].setText(str(exc))
            self._failure('FLIP_CONNECT '+name,str(exc))

    def _connect(self):return self._connect_named(self.selected.currentText())

    def _connect_all(self):
        try:
            self._guard()
            if self._bulk_active:return
            if self._discovering or self._listed_endpoint!=self.endpoint() or not self._server_names:
                raise RuntimeError('서버 flipper 목록을 먼저 불러오세요.')
            if any(w.has_requests() for w in self.workers.values()):raise RuntimeError('Flipper 작업 완료 후 연결하세요.')
            self._bulk_endpoint=self.endpoint();self._bulk_queue=deque(self._server_names)
            self._bulk_failed=[];self._bulk_active=True;self._pump_connect_all()
        except Exception as exc:self._failure('FLIP_CONNECT_ALL',str(exc))

    def _pump_connect_all(self):
        if not self._bulk_active:return
        if self._bulk_handle is not None:
            if not self._bulk_handle.done.is_set():return
            error=self._bulk_handle.error;self._bulk_handle=None
            if error:
                self._bulk_failed.append(self._bulk_name)
                if isinstance(error,TimeoutError) or 'Server did not reply before timeout' in str(error):
                    self._bulk_queue.clear();self._bulk_active=False
                    self.state.setText('서버 응답 timeout으로 전체 연결 중지. 각 장비 오류와 서버 상태를 확인하세요.');return
        if self._closing or self._bulk_endpoint!=self.endpoint() or self.oven.task.running() or self.routing.task.running():
            self._bulk_queue.clear();self._bulk_active=False;return
        while self._bulk_queue:
            name=self._bulk_queue.popleft()
            if self._connected_name(name):continue
            self._bulk_name=name;self.state.setText('전체 연결 중: '+name)
            self._bulk_handle=self._connect_named(name)
            if self._bulk_handle is not None:return
            self._bulk_failed.append(name)
        self._bulk_active=False
        connected=sum(self._connected_name(n) for n in self._server_names)
        self.state.setText(f'Flipper {connected} / {len(self._server_names)} 연결'+(' · 실패: '+', '.join(self._bulk_failed) if self._bulk_failed else ''))

    def _selected_action(self,action,position=None):
        return self._named_action(self.selected.currentText(),action,position)

    def _named_action(self,name,action,position=None):
        try:
            self._guard();worker=self.workers[name]
            if self._bulk_active:raise RuntimeError('Wait for flipper connections to finish')
            if worker.has_requests():raise RuntimeError('Wait for this flipper operation to finish')
            self.cards[name]['error']=''
            if action=='DISCONNECT':DeviceAPI(worker).disconnect();return
            if worker._execution_device is None or worker._execution_device[:2]!=self.endpoint():
                raise RuntimeError('Reconnect the flipper to the current main server')
            def execute(w):
                self._guard()
                if w._execution_device[:2]!=self._current_endpoint:raise RuntimeError('Main server changed; reconnect flipper')
                return move(w.ps,position) if action=='MOVE' else Context().acquire(w.ps.position)
            DeviceAPI(worker)._submit('FLIP_'+action,execute)
        except Exception as exc:self._failure('FLIP',str(exc))

    def _result(self,name,handle):
        if not handle.done.is_set():return
        worker=self.workers[name]
        state='오류 · 위치 미확인' if handle.error else ('Disconnected' if worker.ps is None else 'Connected · 위치 읽기 필요')
        if handle.error is None and handle.action in ('FLIP_MOVE','FLIP_READ','FLIP_ROUTE_MOVE'):
            state='이동 중 / 미확인' if handle.result==0 else 'Position '+str(handle.result)
        self.cards[name]['error']=str(handle.error) if handle.error else ''
        self.cards[name]['status'].setText((state+' · '+str(handle.error)) if handle.error else state)

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
        self._pump_connect_all()
        active=self._closing or self._bulk_active or self.oven.task.running() or self.routing.task.running()
        worker=self.workers.get(self.selected.currentText())
        idle=not active and not self._discovering and worker is not None and not worker.has_requests()
        self.connect_button.setEnabled(idle and self.selected.currentText() in self._server_names and self._listed_endpoint==self.endpoint());self.selected.setEnabled(not active and not self._discovering)
        self.disconnect_button.setEnabled(idle and worker is not None and worker.ps is not None)
        for b in (self.pos1,self.pos2,self.read_button):b.setEnabled(idle and self.selected.currentText() in self._server_names and worker is not None and worker.ps is not None and worker._execution_device is not None and worker._execution_device[:2]==self.endpoint() and not worker.connection_error)
        self.discover_button.setEnabled(not active and not self._discovering and not any(w.has_requests() for w in self.workers.values()))
        self.route_settings_button.setEnabled(not active and not self._discovering and self._listed_endpoint==self.endpoint())
        from labremote.ui.connection_status import connection_color
        from labremote.runtime.parameters import LIBRARY
        self.connect_all_button.setEnabled(not active and not self._discovering and bool(self._server_names) and self._listed_endpoint==self.endpoint() and not any(w.has_requests() for w in self.workers.values()))
        count=sum(self._connected_name(n) for n in self._server_names)
        connection_color(self.connect_all_button,'connected' if self._server_names and count==len(self._server_names) else 'partial' if count else 'disconnected')
        for name,card in self.cards.items():
            w=self.workers[name];buttons=card['buttons'];ready=self._connected_name(name)
            idle=not active and not self._discovering and not w.has_requests()
            listed=name in self._server_names and self._listed_endpoint==self.endpoint()
            buttons['connect'].setEnabled(idle and listed and not ready)
            buttons['disconnect'].setEnabled(idle and w.ps is not None)
            for key in ('read','pos1','pos2'):buttons[key].setEnabled(idle and listed and ready)
            connection_color(buttons['connect'],'connected' if ready else 'error' if card['error'] else 'disconnected')
            state=LIBRARY.read((w._execution_device,'position'))
            position=state.observed if ready and not w.has_requests() and state.quality=='valid' and state.verification not in ('pending','failed','mismatch') else None
            for value,key in ((1,'pos1'),(2,'pos2')):connection_color(buttons[key],'connected' if position==value else 'disconnected')
            if not card['error'] and not w.has_requests():
                card['status'].setText(('Position '+str(position) if position in (1,2) else '연결됨 · 위치 미확인') if ready else 'Disconnected'+(' / 현재 서버 목록에 없음' if not listed else ''))
        relay=self.oven.relays
        self.shutter_connect.setEnabled(not active and not relay.has_requests())
        for b in (self.shutter_read,self.shutter_open,self.shutter_close):b.setEnabled(not active and not relay.has_requests() and relay.ps is not None and not relay.io_fault)
        for b in (self.ea,self.ec):b.setEnabled(not active)

    def shutdown(self):
        self._closing=True;self._bulk_queue.clear();self.timer.stop();self.routing.task.cancel();self.discoverer.shutdown()
        for worker in self.workers.values():worker.shutdown()

    def still_running(self):return self.discoverer.isRunning() or self.routing.task.running() or any(w.isRunning() for w in self.workers.values())

    def lifecycle_panels(self):
        return [SimpleNamespace(worker=w,shutdown=self.shutdown,still_running=self.still_running) for w in (self.discoverer,*self.workers.values())]
