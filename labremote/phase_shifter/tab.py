"""FPGA / etc: phase-shifter Ramsey setup, execution and live results."""
import json
from pathlib import Path
from PyQt5 import QtCore, QtWidgets
from labremote.data_paths import tab_data_directory
from . import config
from .selectors import PhaseShifterEtcTab


class PhaseShifterTab(QtWidgets.QWidget):
    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self.worker = worker
        self.runner = worker.phase_shifter_runner
        self.fields = {}
        self.run_id = None
        self.points = []
        root = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel('Phase Shifter Ramsey')
        heading.setStyleSheet('font-size: 20px; font-weight: 600;')
        root.addWidget(heading)
        root.addWidget(QtWidgets.QLabel('0 출력 → 안정화 → π/2 → 위상 변경 → 안정화 → π/2 → 검출'))
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        root.addWidget(split, 1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(440)
        settings = QtWidgets.QWidget()
        self.settings_panel = QtWidgets.QTabWidget()
        left = QtWidgets.QVBoxLayout(settings)
        scroll.setWidget(settings)
        split.addWidget(self.settings_panel)
        self.settings_panel.addTab(scroll, '실험 설정')
        mapping_scroll = QtWidgets.QScrollArea()
        mapping_scroll.setWidgetResizable(True)
        mapping_page = QtWidgets.QWidget()
        mapping_layout = QtWidgets.QVBoxLayout(mapping_page)
        mapping_scroll.setWidget(mapping_page)
        self.settings_panel.addTab(mapping_scroll, '출력 nickname')

        self.mapping = PhaseShifterEtcTab(config.hd)
        mapping_layout.addWidget(self.mapping)
        slow_count = sum(pin.startswith(('jc_', 'jd_')) for pin in config.hd.output_mapping.values())
        self.definition_label = QtWidgets.QLabel(
            f'Hardware definition: {Path(config.hd.__file__).name}\n'
            f'등록된 slow output nickname: {slow_count}개 · 위상 비트 12개 선택 필요')
        self.definition_label.setWordWrap(True)
        mapping_layout.addWidget(self.definition_label)
        mapping_layout.addStretch()
        scan = self._group(left, '위상 스캔 · 각도 설정')
        for key, title, low, high in [('scan_start_deg', '시작 각도', 0, 360),
                ('scan_stop_deg', '끝 각도 (포함)', 0, 360), ('scan_step_deg', '각도 간격', .000001, 360),
                ('phase_angle_deg', '단일 측정 각도', 0, 360)]:
            self._field(scan, key, title, low, high, degrees=True)
        for key, title, low, high in [('N_average', '각도당 반복 횟수', 1, 65535),
                ('threshold', 'Bright 기준 (counts ≥)', 0, 65535)]:
            self._field(scan, key, title, low, high)
        self.scan_summary = QtWidgets.QLabel()
        self.scan_summary.setWordWrap(True)
        scan.addRow(self.scan_summary)
        self.angle_summary = QtWidgets.QLabel()
        self.angle_summary.setWordWrap(True)
        scan.addRow(self.angle_summary)
        model_note = QtWidgets.QLabel('변환 기준: 360° / 4096단계 (약 0.087891°/단계)\n'
                                     '최근접 코드 적용 · 360°는 0°와 동일 출력\n'
                                     '적용 각도는 선형 변환의 명목값이며 실측값이 아닙니다.')
        model_note.setWordWrap(True)
        scan.addRow(model_note)
        timing = self._group(left, '펄스 및 위상 안정화')
        for key, title in [('half_pi_time', 'π/2 펄스 길이'),
                ('phase_zero_settle_clocks', '첫 π/2 전 0° 안정화'),
                ('phase_settle_clocks', '위상 변경 후 안정화')]:
            self._field(timing, key, title, 3, 65538, microseconds=True)
        self._field(timing, 'timeout_s', '각도당 Timeout', .1, 600, seconds=True)
        timing_note = QtWidgets.QLabel('안정화 시간: 위상 출력 갱신부터 다음 π/2 시작까지\n'
                                      '두 안정화 시간을 독립 설정 · 단위 µs · 분해능 0.01 µs')
        timing_note.setWordWrap(True)
        timing.addRow(timing_note)
        advanced = self._group(left, '냉각 · 초기화 · 검출')
        for key, title in [('T_cool', '냉각 대기'), ('T_init', '초기화 대기'),
                           ('T_det', '검출 대기'), ('T_wait_for_aom_off', 'AOM OFF 대기')]:
            self._field(advanced, key, title, 0, 65535, microseconds=True)
        self._field(advanced, 'T_cool_repeat', '냉각 반복', 1, 65535)
        self._field(advanced, 'T_det_repeat', '검출 반복', 1, 65535)
        note = QtWidgets.QLabel('냉각·검출 시간에는 기존 sequencer의 wait 및 반복 명령 시간이 추가됩니다.\n'
                               '처음 표시되는 타이밍과 threshold는 예시값입니다. 실험값으로 조정하세요.')
        note.setWordWrap(True)
        left.addWidget(note)
        left.addStretch()

        right_widget = QtWidgets.QWidget()
        right = QtWidgets.QVBoxLayout(right_widget)
        split.addWidget(right_widget)
        split.setSizes([500, 730])
        buttons = QtWidgets.QHBoxLayout()
        right.addLayout(buttons)
        self.load_button = QtWidgets.QPushButton('설정 불러오기')
        self.save_button = QtWidgets.QPushButton('설정 저장')
        self.validate_button = QtWidgets.QPushButton('시퀀스 검증')
        for button, callback in [(self.load_button, self.load), (self.save_button, self.save),
                                 (self.validate_button, self.validate_sequence)]:
            buttons.addWidget(button)
            button.clicked.connect(callback)
        folder_row = QtWidgets.QHBoxLayout()
        right.addLayout(folder_row)
        self.directory = QtWidgets.QLineEdit(str(tab_data_directory(None, 'phase_shifter')))
        self.folder_button = QtWidgets.QPushButton('저장 폴더')
        self.folder_button.clicked.connect(self.choose_folder)
        folder_row.addWidget(self.directory, 1)
        folder_row.addWidget(self.folder_button)
        actions = QtWidgets.QHBoxLayout()
        right.addLayout(actions)
        self.single_button = QtWidgets.QPushButton('단일 각도 측정')
        self.start_button = QtWidgets.QPushButton('위상 스캔 시작')
        self.stop_button = QtWidgets.QPushButton('중지 · 부분 결과 보존')
        self.single_button.clicked.connect(lambda: self.start(True))
        self.start_button.clicked.connect(lambda: self.start(False))
        self.stop_button.clicked.connect(self.runner.cancel)
        for button in (self.single_button, self.start_button, self.stop_button):
            actions.addWidget(button)
        self.readiness = QtWidgets.QLabel()
        self.readiness.setWordWrap(True)
        right.addWidget(self.readiness)
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        right.addWidget(self.progress_bar)
        self.status = QtWidgets.QLabel('대기 중 · 아직 측정한 데이터가 없습니다.')
        self.status.setWordWrap(True)
        right.addWidget(self.status)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        self.figure = Figure(figsize=(7, 4), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumSize(400, 260)
        right.addWidget(self.canvas, 1)
        self.axis = self.figure.add_subplot(111)
        self.axis.set_xlabel('Requested phase (°)')
        self.axis.set_ylabel('Bright probability')
        self.axis.set_xlim(0, 360)
        self.axis.set_xticks([0, 90, 180, 270, 360])
        self.axis.set_ylim(-.03, 1.03)
        self.axis.grid(True, alpha=.2)
        self.curve, = self.axis.plot([], [], 'o-', color='#346dcb', markersize=4)
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['요청 (°)', '적용 (°)', 'Code', 'Shots', 'P(bright)', 'Mean counts'])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setMaximumHeight(190)
        right.addWidget(self.table)
        self.open_result_button = QtWidgets.QPushButton('저장된 결과 열기')
        self.open_result_button.clicked.connect(self.open_result)
        right.addWidget(self.open_result_button)
        self.mapping.selection_changed.connect(self.controls)
        worker.task_progress.connect(self.progress)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.controls)
        self.timer.start()
        self.controls()

    @staticmethod
    def _group(layout, title):
        group = QtWidgets.QGroupBox(title)
        layout.addWidget(group)
        return QtWidgets.QFormLayout(group)

    def _field(self, layout, key, title, low, high, microseconds=False, seconds=False, degrees=False):
        fractional = microseconds or seconds or degrees
        field = QtWidgets.QDoubleSpinBox() if fractional else QtWidgets.QSpinBox()
        scale = 100 if microseconds else 1
        if fractional:
            field.setDecimals(6 if degrees else 2 if microseconds else 1)
            field.setSingleStep(.01 if microseconds else 1.)
            field.setSuffix(' °' if degrees else ' µs' if microseconds else ' s')
        field.setRange(low/scale, high/scale) if fractional else field.setRange(low, high)
        field.setValue(config.DEFAULTS[key]/scale if fractional else config.DEFAULTS[key])
        field.setProperty('scale', scale)
        field.valueChanged.connect(self.controls)
        self.fields[key] = field
        layout.addRow(title, field)

    def value(self):
        values = {key: (field.value() if key == 'timeout_s' or key.endswith('_deg') else
                        round(field.value()*field.property('scale')))
                  for key, field in self.fields.items()}
        return self.mapping.apply_to(values)

    def controls(self, *_):
        if not hasattr(self, 'start_button'):
            return
        active = self.runner.running()
        error = ''
        try:
            plan = config.scan_points({key: self.fields[key].value()
                                       for key in ('scan_start_deg', 'scan_stop_deg', 'scan_step_deg')})
            n = len(plan)
            repeated = sum(a['code'] == b['code'] for a, b in zip(plan, plan[1:]))
            self.scan_summary.setText(f'{n}개 각도 · 총 {n*self.fields["N_average"].value():,} shots' +
                (f'\n연속 {repeated}지점은 양자화로 동일한 코드가 적용됩니다.' if repeated else ''))
            target = config.phase_point(self.fields['phase_angle_deg'].value())
            self.angle_summary.setText(f'단일 측정: 요청 {target["requested_angle_deg"]:g}° → '
                f'적용 {target["applied_angle_deg"]:.6f}° (코드 {target["code"]})')
        except (ValueError, KeyError) as exc:
            error = str(exc)
            self.scan_summary.setText(error)
        try:
            self.mapping.selection()
        except ValueError as exc:
            error = error or str(exc)
        ready = self.worker.ps is not None and not self.worker.connection_error and not self.worker._closing
        busy = (self.worker.has_requests() or self.worker.waveform_runner.running() or
                any(task.running() for task in self.worker._background_tasks))
        self.readiness.setText(error or ('FPGA 연결 필요' if not ready else
                               'FPGA 작업 중' if busy else '실행 준비 완료'))
        for button in (self.single_button, self.start_button):
            button.setEnabled(not error and ready and not busy and not active)
        self.stop_button.setEnabled(active)
        for widget in (self.settings_panel, self.load_button, self.save_button, self.validate_button,
                       self.directory, self.folder_button, self.open_result_button):
            widget.setEnabled(not active)

    def validate_sequence(self):
        try:
            config.validate(self.value())
            self.status.setText('검증 통과 · nickname, 출력 중복, 타이밍, sequencer 명령 확인 완료')
        except Exception as exc:
            self.status.setText(str(exc))

    def populate(self, value):
        # Validate before changing the current form; retain no stale nicknames.
        value = config.validate(value)
        for key, field in self.fields.items():
            field.setValue(value[key]/field.property('scale') if isinstance(field, QtWidgets.QDoubleSpinBox) else value[key])
        for role, combo in self.mapping.output_selectors.items():
            combo.setCurrentIndex(combo.findData(value['outputs'][role]))
        for combo, name in zip(self.mapping.phase_selectors, value['phase_outputs']):
            combo.setCurrentIndex(combo.findData(name))
        combo = self.mapping.detector_selector
        combo.setCurrentIndex(combo.findData(value['detector_nickname']))
        self.controls()

    def save(self):
        try:
            value = config.validate(self.value())
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, '설정 저장', 'phase_shifter.json', 'JSON (*.json)')
            if path:
                Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
                self.status.setText('설정 저장: ' + path)
        except Exception as exc:
            self.status.setText(str(exc))

    def load(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, '설정 불러오기', '', 'JSON (*.json)')
        if path:
            try:
                self.populate(json.loads(Path(path).read_text(encoding='utf-8')))
                self.status.setText('설정 불러옴: ' + path)
            except Exception as exc:
                self.status.setText(str(exc))

    def choose_folder(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, '결과 저장 폴더', self.directory.text())
        if path:
            self.directory.setText(path)

    def start(self, single=False):
        try:
            if not self.directory.text().strip():
                raise ValueError('결과 저장 폴더를 지정하세요.')
            handle = self.runner.start(self.value(), directory=self.directory.text(), single=single)
            self.run_id = handle.request_id
            self.render_points([])
            self.status.setText(str(handle.error) if handle.done.is_set() and handle.error else '측정 시작')
        except Exception as exc:
            self.status.setText(str(exc))
        self.controls()

    def progress(self, label, state):
        if label != self.runner.label or state.get('run_id') != self.run_id:
            return
        points = state.get('points', [])
        if points != self.points:
            self.render_points(points)
        self.progress_bar.setRange(0, state.get('total', 1))
        self.progress_bar.setValue(len(points))
        self.status.setText(' · '.join(str(x) for x in [state.get('phase', ''),
                            state.get('error', ''), state.get('folder', '')] if x))
        self.controls()

    def render_points(self, points):
        self.points = [dict(point) for point in points]
        self.curve.set_data([p.get('requested_angle_deg', p['code'] * config.DEGREES_PER_CODE)
                             for p in points], [p['probability'] for p in points])
        self.canvas.draw_idle()
        self.table.setRowCount(len(points))
        for row, point in enumerate(points):
            requested = point.get('requested_angle_deg', point['code'] * config.DEGREES_PER_CODE)
            applied = point.get('applied_angle_deg', point['code'] * config.DEGREES_PER_CODE)
            for col, value in enumerate((f'{requested:.6f}', f'{applied:.6f}', point['code'], point['shots'],
                                        f'{point["probability"]:.4f}', f'{point["mean_count"]:.2f}')):
                self.table.setItem(row, col, QtWidgets.QTableWidgetItem(str(value)))

    def open_result(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, '결과 열기', self.directory.text(), 'Result (result.json)')
        if path:
            try:
                result = json.loads(Path(path).read_text(encoding='utf-8'))
                self.render_points(result['points'])
                self.progress_bar.setRange(0, len(result['codes']))
                self.progress_bar.setValue(len(result['points']))
                self.status.setText(f'{result["status"]} · {path}')
            except Exception as exc:
                self.status.setText(str(exc))

    def shutdown(self):
        self.timer.stop()
        if self.runner.running():
            self.runner.cancel()
