"""CCD-side controls; no device reads/waits on the GUI thread."""
from types import SimpleNamespace
from PyQt5 import QtCore, QtWidgets
from labremote.api.devices import DeviceAPI
from labremote.operation.oven_psu import control as power
from labremote.operation.oven_relay import control as relay
from .worker import OvenPSUWorker, OvenRelayWorker
from .runner import OvenLoadTask
from .settings import load_settings, save_settings, PROFILES


class OvenPanel(QtWidgets.QGroupBox):
    log_message = QtCore.pyqtSignal(str)
    active_changed = QtCore.pyqtSignal(bool)

    def __init__(self, ccd_panel, endpoint, parent=None):
        super().__init__('Oven · CH1', parent)
        self.ccd_panel, self.endpoint = ccd_panel, endpoint
        self.psu, self.relays = OvenPSUWorker(), OvenRelayWorker()
        self.task = OvenLoadTask(self.psu, self.relays, ccd_panel.worker)
        self.handle = None
        self.read_handle = None
        self._closing = False
        self._stop_requested = False
        self._last_handle = None
        self._idle_stop_barriers = []
        config_error = ''
        try:config = load_settings()
        except Exception as exc:
            from .settings import DEFAULTS
            config = dict(DEFAULTS);config_error = str(exc)
        self._config_error=config_error
        self.chamber=config['chamber']
        self.setTitle(f'{self.chamber} oven · CH1 · chamber from config' if not config_error else 'Oven · configuration error')
        grid = QtWidgets.QGridLayout(self)
        self.psu_name = QtWidgets.QLineEdit(config['psu_name'])
        self.relay_name = QtWidgets.QLineEdit(config['relay_name'])
        self.psu_name.setParent(self);self.psu_name.hide()
        self.relay_name.setParent(self);self.relay_name.hide()
        self.connect_button = QtWidgets.QPushButton('Connect oven devices')
        self.isotope = QtWidgets.QComboBox();self.isotope.addItems(['171','174'])
        self.shutter = QtWidgets.QComboBox();self.shutter.addItems(['shutter_2','shutter_1'])
        self.shutter.setCurrentText(config['shutter'])
        self.photoionization_shutter=QtWidgets.QComboBox();self.photoionization_shutter.addItems(['shutter_1','shutter_2'])
        self.photoionization_shutter.setCurrentText(config['photoionization_shutter'])
        self.timeout_minutes=QtWidgets.QSpinBox();self.timeout_minutes.setRange(0,9999);self.timeout_minutes.setSuffix(' 분')
        self.timeout_seconds=QtWidgets.QSpinBox();self.timeout_seconds.setRange(0,59);self.timeout_seconds.setSuffix(' 초')
        seconds=config.get('timeout_s',600)
        self.timeout_minutes.setValue(seconds//60);self.timeout_seconds.setValue(seconds%60)
        self.profile = QtWidgets.QLabel()
        self.timeout_minutes.valueChanged.connect(self._profile);self.timeout_seconds.valueChanged.connect(self._profile)
        self.isotope.currentTextChanged.connect(self._profile)
        self._profile()
        self.start_button = QtWidgets.QPushButton('Oven ON · timeout / STOP 종료')
        self.stop_button = QtWidgets.QPushButton('STOP / Oven OFF')
        self.measured = QtWidgets.QLabel('CH1 현재 측정값: — V / — A')
        self.shutter_state=QtWidgets.QLabel('오븐 셔터 위치 미확인')
        self.photo_shutter_state=QtWidgets.QLabel('399 셔터 위치 미확인')
        self.state = QtWidgets.QLabel(config_error or '검출 ON: 포획 / timeout / STOP 종료 · 검출 OFF: timeout / STOP 종료')
        self.state.setWordWrap(True)
        warning = QtWidgets.QLabel('E3631A OFF는 전체 출력에 적용됩니다. CH2/CH3는 0으로 설정합니다. Flipper 자동 전환은 로컬 매핑을 활성화한 경우에만 수행합니다.')
        warning.setWordWrap(True)
        for row,(label,widget) in enumerate(((f'{self.chamber} isotope',self.isotope),('Oven shutter',self.shutter),('399 shutter',self.photoionization_shutter))):
            grid.addWidget(QtWidgets.QLabel(label),row,0);grid.addWidget(widget,row,1)
        timeout_row=QtWidgets.QHBoxLayout();timeout_row.addWidget(self.timeout_minutes);timeout_row.addWidget(self.timeout_seconds)
        grid.addWidget(QtWidgets.QLabel('Timeout'),3,0);grid.addLayout(timeout_row,3,1)
        grid.addWidget(self.shutter_state,4,0);grid.addWidget(self.photo_shutter_state,4,1)
        for row,widget in enumerate((self.profile,warning,self.connect_button),5):grid.addWidget(widget,row,0,1,2)
        grid.addWidget(self.start_button,8,0);grid.addWidget(self.stop_button,8,1)
        grid.addWidget(self.measured,9,0,1,2);grid.addWidget(self.state,10,0,1,2)
        self.connect_button.clicked.connect(self._connect)
        self.start_button.clicked.connect(self._start)
        self.stop_button.clicked.connect(self._stop)
        for worker in (self.psu,self.relays):
            worker.failure.connect(self._failure)
            worker.connected.connect(lambda _:self._connected())
            worker.disconnected.connect(lambda message:self._failure('OVEN',message))
            worker.start()
        self.psu.task_changed.connect(self._task_changed)
        self.psu.task_progress.connect(lambda label,state:self._progress(state))
        self.psu.handle_changed.connect(self._operation_changed)
        self.relays.handle_changed.connect(self._operation_changed)
        self.timer = QtCore.QTimer(self);self.timer.setInterval(250)
        self.timer.timeout.connect(self._tick);self.timer.start()
        self._next_read = 0

    def _profile(self):
        voltage,current=PROFILES[self.chamber+'_'+self.isotope.currentText()]
        self.profile.setText(f'{self.chamber} · CH1 설정 제한: {voltage:.3f} V / {current:.2f} A · timeout {self.timeout_minutes.value()}분 {self.timeout_seconds.value()}초')

    def _config(self):
        if self._config_error:raise ValueError(self._config_error)
        return dict(chamber=self.chamber,psu_name=self.psu_name.text().strip(),relay_name=self.relay_name.text().strip(),
                    shutter=self.shutter.currentText(),photoionization_shutter=self.photoionization_shutter.currentText(),timeout_s=self.timeout_minutes.value()*60+self.timeout_seconds.value())

    def _connect(self):
        if self.task.running() or self.psu.has_requests() or self.relays.has_requests():return
        try:
            config=self._config()
            if not config['psu_name'] or not config['relay_name'] or config['psu_name']==config['relay_name']:
                raise ValueError('Enter distinct PSU and relay instrument names')
            save_settings(config)
            host,port=self.endpoint()
            DeviceAPI(self.psu).connect(host,port,config['psu_name'])
            DeviceAPI(self.relays).connect(host,port,config['relay_name'])
            self.state.setText('Connecting to InstrumentServer devices…')
        except Exception as exc:self._failure('OVEN_CONNECT',str(exc))

    def _connected(self):
        if all(w.ps is not None and not w.io_fault and not w.connection_error for w in (self.psu,self.relays)):
            self.state.setText('Oven devices connected · live readback verified · output unchanged')

    def _start(self):
        if self.task.running():return
        try:
            save_settings(self._config())
            panel=self.ccd_panel
            detection=panel._detection_enabled
            if detection and panel.detection_roi() is None:raise ValueError('CCD 화면에 센서 이미지를 표시하세요.')
            self.handle=self.task.start(int(self.isotope.currentText()),chamber=self.chamber,shutter=self.shutter.currentText(),
                threshold=panel.threshold.value(),min_area=panel.area.value(),
                target=panel.target.value(),consecutive_frames=panel.consecutive.value(),
                roi=panel.detection_roi() if detection else None, follow_viewport=detection,
                detect_ions=detection,photoionization_shutter=self.photoionization_shutter.currentText(),timeout_s=self.timeout_minutes.value()*60+self.timeout_seconds.value())
            self._tick()
        except Exception as exc:self._failure('OVEN_LOAD',str(exc))

    def _stop(self):
        if self.task.running():
            self.task.cancel();self.state.setText('Stopping oven; waiting for OFF/CLOSE verification…')
        else:
            # Even idle STOP closes 399 first; failure must not suppress PSU OFF.
            import threading
            shutter=self.shutter.currentText();photo=self.photoionization_shutter.currentText()
            guard=threading.Lock();submitted=[False]
            barrier=threading.Event();self._idle_stop_barriers.append(barrier)
            def after_close(handle):
                if not handle.done.is_set():return
                with guard:
                    if submitted[0]:return
                    submitted[0]=True
                try:
                    DeviceAPI(self.psu)._submit('OVEN_OFF',lambda w:power.off(w.ps))
                    if shutter!=photo:
                        DeviceAPI(self.relays)._submit('OVEN_SHUTTER_CLOSE',lambda w:relay.close_shutter(w.ps,shutter))
                finally:barrier.set()
            closed=DeviceAPI(self.relays)._submit('OVEN_399_CLOSE',lambda w:relay.close_shutter(w.ps,photo))
            closed.subscribe(after_close)

    def _failure(self,label,error):
        from labremote.runtime.errors import OperationCancelled
        from .runner import OvenTimeout
        if label=='OVEN_LOAD' and str(error).startswith(('OvenTimeout:', 'OperationCancelled:')) and self.task.handle is not None and isinstance(self.task.handle.error,(OvenTimeout,OperationCancelled)) and self.task.state.get('cleanup_confirmed'):
            self._task_changed(label,self.task.handle);return
        self.measured.setText('CH1 현재 측정값: 조회 실패 (유효한 값 없음)')
        self.state.setText(f'{label}: {error}\n장비 오류 시 자동 조회/ON 중지. 서버 연결 복구 후 Connect oven devices를 다시 누르세요.')
        self.log_message.emit(f'{label}: {error}')

    def _task_changed(self,label,handle):
        self.handle=handle
        if handle.done.is_set():
            from labremote.runtime.errors import OperationCancelled
            from .runner import OvenTimeout
            if handle.error and not (isinstance(handle.error,(OvenTimeout,OperationCancelled)) and self.task.state.get('cleanup_confirmed')):
                self._failure(label,str(handle.error))
            else:
                reason='STOP' if isinstance(handle.error,OperationCancelled) else 'Timeout' if isinstance(handle.error,OvenTimeout) or (handle.result or {}).get('stop_reason')=='timeout' else 'Ion condition met'
                self.state.setText(reason+' · PSU OFF / shutter CLOSED 확인')

    def _progress(self,state):
        if 'voltage_v' in state and 'current_a' in state:
            self.measured.setText(f"CH1 현재 측정값: {state['voltage_v']:.4f} V / {state['current_a']:.4f} A · {state.get('output','')}")
        if 'phase' in state:
            phase=state['phase']
            if 'remaining_s' in state:
                remaining=max(0,int(state["remaining_s"]));phase+=f" · {remaining//60}분 {remaining%60}초 남음"
            if state.get('error'):phase+=' · '+state['error']
            self.state.setText(phase)

    def _operation_changed(self,handle):
        if handle.done.is_set() and handle.error is None and handle.action=='OVEN_READBACK' and handle.result is not None:
            self._progress(handle.result)

    def _tick(self):
        import time
        active=self.task.running()
        self.active_changed.emit(active)
        for widget in (self.connect_button,self.psu_name,self.relay_name,self.isotope,self.shutter,self.photoionization_shutter,self.timeout_minutes,self.timeout_seconds):
            widget.setEnabled(not active and not self._closing)
        ready=all(w.ps is not None and not w.connection_error and not w.io_fault and not w._closing for w in (self.psu,self.relays))
        from labremote.ui.connection_status import connection_color
        connection_color(self.connect_button, 'connected' if ready else 'disconnected')
        detection=self.ccd_panel._detection_enabled
        self.start_button.setText('Oven ON · 포획 시 자동 종료' if detection else 'Oven ON · timeout / STOP 종료')
        self.start_button.setEnabled(not getattr(self,'_config_error','') and ready and (not detection or self.ccd_panel.connected) and not active and not self._closing and self.ccd_panel._start_after_detection is None)
        from labremote.ui.shutter_status import show_shutter
        show_shutter(self.shutter_state,self.relays,self.shutter.currentText())
        show_shutter(self.photo_shutter_state,self.relays,self.photoionization_shutter.currentText())
        self._idle_stop_barriers=[event for event in getattr(self,'_idle_stop_barriers',[]) if not event.is_set()]
        if self._closing:
            if not active and not self._stop_requested and not self._idle_stop_barriers and not any(w.has_requests() for w in (self.psu,self.relays)):
                self._stop_requested=True
                for worker in (self.psu,self.relays):worker.shutdown()
            if not self.still_running():self.timer.stop()
            return
        if not active and ready and time.monotonic()>=self._next_read and not self.psu.has_requests():
            self._next_read=time.monotonic()+2
            from labremote.runtime.auto_monitor import AUTO_MONITOR
            AUTO_MONITOR.request(self.psu, ('OVEN_READBACK',lambda w:power.read_snapshot(w.ps)))

    def shutdown(self):
        self._closing=True
        self.task.cancel()
        self._tick()

    def still_running(self):
        return self.task.running() or self.psu.isRunning() or self.relays.isRunning()

    def lifecycle_panels(self):
        # Register both device queues with the existing main-window shutdown gate.
        return [SimpleNamespace(worker=w,shutdown=self.shutdown,still_running=self.still_running) for w in (self.psu,self.relays)]
