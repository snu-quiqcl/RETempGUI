"""Manual phase hold UI. All writes run on the existing FPGA worker."""
import json
from pathlib import Path
from PyQt5 import QtCore, QtWidgets
from . import config, hold
from .calibration import CalibrationSelector


class PhaseHoldTab(QtWidgets.QWidget):
    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self.worker = worker
        self.pending = None
        self.last_result = None
        self.output_uncertain = False
        root = QtWidgets.QHBoxLayout(self)
        self.mapping_group = QtWidgets.QGroupBox('Hardware definition · nickname 선택')
        grid = QtWidgets.QGridLayout(self.mapping_group)
        root.addWidget(self.mapping_group, 2, QtCore.Qt.AlignTop)
        self.selectors = []
        names = [name for name, pin in config.hd.output_mapping.items()
                 if pin.startswith(('jc_', 'jd_'))]
        for i in range(12):
            combo = QtWidgets.QComboBox()
            combo.addItem('— nickname 선택 —', None)
            for name in names:
                combo.addItem(name, name)
            self.selectors.append(combo)
            col = (i // 6) * 2
            grid.addWidget(QtWidgets.QLabel(f'D{i}'), i % 6, col)
            grid.addWidget(combo, i % 6, col + 1)
            combo.currentIndexChanged.connect(self.controls)
        grid.addWidget(QtWidgets.QLabel('D0 = LSB · D11 = MSB'), 6, 0, 1, 4)
        self.load_button = QtWidgets.QPushButton('설정 불러오기')
        self.save_button = QtWidgets.QPushButton('설정 저장')
        self.load_button.clicked.connect(self.load)
        self.save_button.clicked.connect(self.save)
        grid.addWidget(self.load_button, 7, 0, 1, 2)
        grid.addWidget(self.save_button, 7, 2, 1, 2)
        right = QtWidgets.QVBoxLayout()
        root.addLayout(right, 3)
        self.calibration = CalibrationSelector()
        right.addWidget(self.calibration)
        self.calibration.changed.connect(self.controls)
        title = QtWidgets.QLabel('고정할 위상')
        title.setStyleSheet('font-size: 22px; font-weight: 600;')
        right.addWidget(title)
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setRange(0, 360)
        self.angle.setDecimals(6)
        self.angle.setSuffix(' °')
        self.angle.setValue(90)
        self.angle.setStyleSheet('font-size: 28px; padding: 10px;')
        self.angle.valueChanged.connect(self.controls)
        right.addWidget(self.angle)
        self.converted = QtWidgets.QLabel()
        right.addWidget(self.converted)
        note = QtWidgets.QLabel('선형: 명목 각도 / 보정표: 조건부 추정 각도 · 실제 RF 위상 측정값은 아닙니다.')
        note.setWordWrap(True)
        right.addWidget(note)
        buttons = QtWidgets.QHBoxLayout()
        right.addLayout(buttons)
        self.apply_button = QtWidgets.QPushButton('위상 적용')
        self.zero_button = QtWidgets.QPushButton('0° 복원')
        self.apply_button.clicked.connect(lambda: self.send(self.angle.value()))
        self.zero_button.clicked.connect(lambda: self.send(0.))
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.zero_button)
        self.readiness = QtWidgets.QLabel()
        self.readiness.setWordWrap(True)
        right.addWidget(self.readiness)
        right.addWidget(QtWidgets.QLabel('적용한 출력은 다음 변경 명령 또는 FPGA 리셋까지 유지됩니다.'))
        status_group = QtWidgets.QGroupBox('출력 상태 · 마지막 전송 명령 기준')
        form = QtWidgets.QFormLayout(status_group)
        self.last_angle = QtWidgets.QLabel('—')
        self.last_code = QtWidgets.QLabel('—')
        self.status = QtWidgets.QLabel('적용 전')
        self.status.setWordWrap(True)
        form.addRow('마지막 전송 각도', self.last_angle)
        form.addRow('마지막 전송 코드', self.last_code)
        form.addRow('상태', self.status)
        right.addWidget(status_group)
        note = QtWidgets.QLabel('실험 실행 중에는 수동 위상 변경이 잠깁니다.\n'
                               'Ramsey는 각 반복의 첫 π/2 전에 위상을 0°로 초기화합니다.\n'
                               '다른 실험이 이 출력 비트를 변경하면 고정값도 바뀝니다.')
        note.setWordWrap(True)
        right.addWidget(note)
        right.addStretch()
        if hasattr(worker, 'disconnected'):
            worker.disconnected.connect(self.invalidate)
        if hasattr(worker, 'connected'):
            worker.connected.connect(self.invalidate)
        if hasattr(worker, 'handle_changed'):
            worker.handle_changed.connect(self.other_command)
        worker.task_progress.connect(self.experiment_progress)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.controls)
        self.timer.start()
        self.controls()

    def names(self):
        return [combo.currentData() for combo in self.selectors]

    def invalidate(self, *_):
        self.output_uncertain = True
        if self.last_result is not None:
            self.status.setText('출력 유지 여부 미확인 · 연결 변경 또는 다른 FPGA 작업 발생')

    def other_command(self, handle):
        if handle.action != 'PHASE_HOLD' and not handle.action.startswith(('MONITOR', 'ACQUIRE')):
            self.invalidate()

    def experiment_progress(self, *_):
        self.invalidate()

    def controls(self, *_):
        if not hasattr(self, 'apply_button'):
            return
        if self.pending is not None and self.pending.done.is_set():
            completed, self.pending = self.pending, None
            if completed.error:
                self.status.setText('적용 실패 · 출력 상태 미확인: ' + str(completed.error))
            else:
                value = completed.result
                self.last_result = value
                self.last_angle.setText(f'{value["requested_angle_deg"]:g}° → 명목/추정 {value["applied_angle_deg"]:.6f}°')
                self.last_code.setText(str(value['code']))
                self.status.setText('전송 완료 · 자동 0° 복원 없음 (물리 출력 readback 아님)')
                if self.output_uncertain:
                    self.invalidate()
        error = ''
        try:
            point = hold.request(self.angle.value(), self.names(), calibration=self.calibration.active())
            self.converted.setText(f'변환 코드: {point["code"]}    명목/추정 각도: {point["applied_angle_deg"]:.6f}°')
        except ValueError as exc:
            error = str(exc)
            self.converted.setText(error)
        zero_error = ''
        try:
            hold.request(0., self.names())
        except ValueError as exc:
            zero_error = str(exc)
        ready = self.worker.ps is not None and not self.worker.connection_error and not self.worker._closing
        locked = self.pending is not None or hold.busy(self.worker) or self.worker.has_requests()
        self.readiness.setText(error or ('FPGA 연결 필요' if not ready else 'FPGA 작업 중' if locked else '적용 준비 완료'))
        self.apply_button.setEnabled(ready and not error and not locked)
        self.zero_button.setEnabled(ready and not zero_error and not locked)
        self.calibration.setEnabled(not locked)
        self.mapping_group.setEnabled(not locked)
        self.angle.setEnabled(not locked)

    def send(self, angle):
        try:
            self.output_uncertain = False
            table = self.calibration.active() if angle != 0 else None
            self.pending = hold.submit(self.worker, angle, self.names(), calibration=table) if table else hold.submit(self.worker, angle, self.names())
            self.status.setText('위상 전송 중…')
        except Exception as exc:
            self.status.setText(str(exc))
        self.controls()

    def save(self):
        try:
            hold.request(self.angle.value(), self.names(), calibration=self.calibration.active())
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, '위상 고정 설정 저장', 'phase_hold.json', 'JSON (*.json)')
            if path:
                Path(path).write_text(json.dumps(dict(phase_angle_deg=self.angle.value(), phase_outputs=self.names(), calibration=self.calibration.active()), indent=2), encoding='utf-8')
        except Exception as exc:
            self.status.setText(str(exc))

    def load(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, '위상 고정 / Ramsey 설정 불러오기', '', 'JSON (*.json)')
        if path:
            try:
                value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
                hold.request(value['phase_angle_deg'], value['phase_outputs'], calibration=value.get('calibration'))
                self.calibration.set_table(value.get('calibration'))
                for combo, name in zip(self.selectors, value['phase_outputs']):
                    combo.setCurrentIndex(combo.findData(name))
                self.angle.setValue(value['phase_angle_deg'])
                self.status.setText('설정 불러옴 · 적용 버튼을 눌러야 출력이 변경됩니다.')
            except Exception as exc:
                self.status.setText(str(exc))

    def shutdown(self):
        self.timer.stop()
        # Closing this view must not issue a zero-phase command.


class EtcTab(QtWidgets.QTabWidget):
    def __init__(self, worker, parent=None):
        super().__init__(parent)
        from .tab import PhaseShifterTab
        self.ramsey = PhaseShifterTab(worker, self)
        self.hold = PhaseHoldTab(worker, self)
        self.addTab(self.ramsey, 'Ramsey 스캔')
        self.addTab(self.hold, '위상 고정')
        # Both modes address the same phase shifter, with one shared mapping.
        for a, b in zip(self.ramsey.mapping.phase_selectors, self.hold.selectors):
            a.currentIndexChanged.connect(lambda _, src=a, dst=b: dst.setCurrentIndex(max(0, dst.findData(src.currentData()))))
            b.currentIndexChanged.connect(lambda _, src=b, dst=a: dst.setCurrentIndex(max(0, dst.findData(src.currentData()))))

    def shutdown(self):
        self.ramsey.shutdown()
        self.hold.shutdown()
