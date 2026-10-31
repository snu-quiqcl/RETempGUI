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
        super().__init__('EC oven · CH1 · auto OFF on ions / 10 min', parent)
        self.ccd_panel, self.endpoint = ccd_panel, endpoint
        self.psu, self.relays = OvenPSUWorker(), OvenRelayWorker()
        self.task = OvenLoadTask(self.psu, self.relays, ccd_panel.worker)
        self.handle = None
        self.read_handle = None
        self._closing = False
        self._stop_requested = False
        self._last_handle = None
        config_error = ''
        try:config = load_settings()
        except Exception as exc:
            from .settings import DEFAULTS
            config = dict(DEFAULTS);config_error = str(exc)
        grid = QtWidgets.QGridLayout(self)
        self.psu_name = QtWidgets.QLineEdit(config['psu_name'])
        self.relay_name = QtWidgets.QLineEdit(config['relay_name'])
        self.connect_button = QtWidgets.QPushButton('Connect oven devices')
        self.isotope = QtWidgets.QComboBox();self.isotope.addItems(['171','174'])
        self.shutter = QtWidgets.QComboBox();self.shutter.addItems(['shutter_2','shutter_1'])
        self.shutter.setCurrentText(config['shutter'])
        self.profile = QtWidgets.QLabel()
        self.isotope.currentTextChanged.connect(self._profile)
        self._profile()
        self.start_button = QtWidgets.QPushButton('Oven ON · load EC ions')
        self.stop_button = QtWidgets.QPushButton('STOP / Oven OFF')
        self.measured = QtWidgets.QLabel('CH1 현재 측정값: — V / — A')
        self.state = QtWidgets.QLabel(config_error or 'Connect oven PSU/relay and real CCD. No automatic connection.')
        self.state.setWordWrap(True)
        warning = QtWidgets.QLabel('E3631A OFF는 전체 출력에 적용됩니다. CH2/CH3는 0으로 설정합니다. Flipper 자동 전환은 로컬 매핑을 활성화한 경우에만 수행합니다.')
        warning.setWordWrap(True)
        for row,(label,widget) in enumerate((('PSU instrument',self.psu_name),('Relay instrument',self.relay_name),('EC isotope',self.isotope),('EC shutter',self.shutter))):
            grid.addWidget(QtWidgets.QLabel(label),row,0);grid.addWidget(widget,row,1)
        for row,widget in enumerate((self.profile,warning,self.connect_button),4):grid.addWidget(widget,row,0,1,2)
        grid.addWidget(self.start_button,7,0);grid.addWidget(self.stop_button,7,1)
        grid.addWidget(self.measured,8,0,1,2);grid.addWidget(self.state,9,0,1,2)
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
        voltage,current=PROFILES['EC_'+self.isotope.currentText()]
        self.profile.setText(f'CH1 설정 제한: {voltage:.3f} V / {current:.2f} A · timeout 600 s')

    def _config(self):
        return dict(psu_name=self.psu_name.text().strip(),relay_name=self.relay_name.text().strip(),
                    shutter=self.shutter.currentText())

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
            self.handle=self.task.start(int(self.isotope.currentText()),shutter=self.shutter.currentText(),
                threshold=panel.threshold.value(),min_area=panel.area.value(),
                target=panel.target.value(),consecutive_frames=panel.consecutive.value(),
                roi=tuple(w.value() for w in panel.roi) if panel.roi_enabled.isChecked() else None)
            self._tick()
        except Exception as exc:self._failure('OVEN_LOAD',str(exc))

    def _stop(self):
        if self.task.running():
            self.task.cancel();self.state.setText('Stopping oven; waiting for OFF/CLOSE verification…')
        else:
            # Manual OFF remains available independently of CCD and task cancellation.
            DeviceAPI(self.psu)._submit('OVEN_OFF',lambda w:power.off(w.ps))
            shutter=self.shutter.currentText()
            DeviceAPI(self.relays)._submit('OVEN_SHUTTER_CLOSE',lambda w:relay.close_shutter(w.ps,shutter))

    def _failure(self,label,error):
        self.measured.setText('CH1 현재 측정값: 조회 실패 (유효한 값 없음)')
        self.state.setText(f'{label}: {error}\n장비 오류 시 자동 조회/ON 중지. 서버 연결 복구 후 Connect oven devices를 다시 누르세요.')
        self.log_message.emit(f'{label}: {error}')

    def _task_changed(self,label,handle):
        self.handle=handle
        if handle.done.is_set():
            if handle.error:self._failure(label,str(handle.error))
            else:self.state.setText('Ion condition met · PSU OFF / EC shutter CLOSED')

    def _progress(self,state):
        if 'voltage_v' in state and 'current_a' in state:
            self.measured.setText(f"CH1 현재 측정값: {state['voltage_v']:.4f} V / {state['current_a']:.4f} A · {state.get('output','')}")
        if 'phase' in state:
            phase=state['phase']
            if 'remaining_s' in state:phase+=f" · {state['remaining_s']:.0f} s remaining"
            if state.get('error'):phase+=' · '+state['error']
            self.state.setText(phase)

    def _operation_changed(self,handle):
        if handle.done.is_set() and handle.error is None and handle.action=='OVEN_READBACK':
            self._progress(handle.result)

    def _tick(self):
        import time
        active=self.task.running()
        self.active_changed.emit(active)
        for widget in (self.connect_button,self.psu_name,self.relay_name,self.isotope,self.shutter):
            widget.setEnabled(not active and not self._closing)
        ready=all(w.ps is not None and not w.connection_error and not w.io_fault and not w._closing for w in (self.psu,self.relays))
        self.start_button.setEnabled(ready and self.ccd_panel.connected and not active and not self._closing)
        if self._closing:
            if not active and not self._stop_requested:
                self._stop_requested=True
                for worker in (self.psu,self.relays):worker.shutdown()
            if not self.still_running():self.timer.stop()
            return
        if not active and ready and time.monotonic()>=self._next_read and not self.psu.has_requests():
            self._next_read=time.monotonic()+2
            self.read_handle=DeviceAPI(self.psu)._submit('OVEN_READBACK',lambda w:power.read_snapshot(w.ps))

    def shutdown(self):
        self._closing=True
        self.task.cancel()
        self._tick()

    def still_running(self):
        return self.task.running() or self.psu.isRunning() or self.relays.isRunning()

    def lifecycle_panels(self):
        # Register both device queues with the existing main-window shutdown gate.
        return [SimpleNamespace(worker=w,shutdown=self.shutdown,still_running=self.still_running) for w in (self.psu,self.relays)]
