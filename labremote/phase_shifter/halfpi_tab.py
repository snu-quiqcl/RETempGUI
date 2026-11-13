"""Linear-phase Ramsey with Rabi-derived pulse widths and independent mapping."""
from pathlib import Path
from PyQt5 import QtWidgets as W
from labremote.devices.fpga.mapping import bound_methods
from .tab import PhaseShifterTab
from . import config,halfpi

@bound_methods(None)
class HalfPiRamseyTab(PhaseShifterTab):
    def __init__(self,worker,parent=None):
        self.halfpi_source=None;self.preview_signature=None;self.auto_ready=False
        super().__init__(worker,parent)
        self.calibration.hide();self.skip_unreliable.hide()
        field=self.fields['half_pi_time'];label=field.parentWidget().layout().labelForField(field)
        if label:label.hide()
        field.hide()
        self.source_group=W.QGroupBox('Rabi 보정 Ramsey · 위상 선형 변환 고정')
        layout=W.QVBoxLayout(self.source_group)
        self.source_button=W.QPushButton('위상별 Rabi 결과 JSON 선택…');layout.addWidget(self.source_button);self.source_button.clicked.connect(self.choose_rabi)
        self.source_label=W.QLabel('원본 Rabi 결과를 선택하세요. π/2 시간은 자동 계산됩니다.');self.source_label.setWordWrap(True);layout.addWidget(self.source_label)
        note=W.QLabel('첫 π/2: 코드 0 · 두 번째 π/2: 목표 코드 · tπ/2 = 250/f(kHz) µs\n'
            '선형 시간 보간 / 10 ns 양자화 · 실패 피팅 통과·외삽 금지\n'
            '주파수 오차 ≤25%, 인접 코드 간격 ≤512, 중복 코드 시간 차이 ≤10%\n'
            'Rabi와 같은 MW 주파수·출력·배선, 공명 조건에서 사용하세요.')
        note.setWordWrap(True);layout.addWidget(note);self.layout().insertWidget(2,self.source_group)
        preview=W.QWidget();pv=W.QVBoxLayout(preview)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        self.halfpi_figure=Figure(figsize=(5,3),tight_layout=True);self.halfpi_canvas=FigureCanvasQTAgg(self.halfpi_figure);pv.addWidget(self.halfpi_canvas)
        self.halfpi_table=W.QTableWidget(0,5);self.halfpi_table.setHorizontalHeaderLabels(['요청 (°)','Code','첫 π/2 (µs)','두 번째 π/2 (µs)','상태'])
        self.halfpi_table.horizontalHeader().setSectionResizeMode(W.QHeaderView.Stretch);self.halfpi_table.setEditTriggers(W.QAbstractItemView.NoEditTriggers);pv.addWidget(self.halfpi_table)
        self.settings_panel.addTab(preview,'π/2 보간 · 적용 시간')
        self.auto_ready=True;self.controls()

    def value(self):
        c=super().value();c.pop('calibration',None);c.pop('skip_unreliable',None)
        if self.halfpi_source is None:raise ValueError('위상별 Rabi 결과 JSON을 먼저 선택하세요.')
        c['halfpi_calibration']=self.halfpi_source
        return c

    def choose_rabi(self):
        path,_=W.QFileDialog.getOpenFileName(self,'위상별 Rabi result.json 선택','','JSON (*.json)')
        if path:
            try:self.set_source(halfpi.load(path));self.settings_panel.setCurrentIndex(2)
            except Exception as exc:self.status.setText(str(exc))
        self.controls()

    def set_source(self,snapshot):
        halfpi.knots(snapshot);self.halfpi_source=snapshot;self.preview_signature=None
        self.source_label.setText(Path(snapshot['path']).name+' · SHA256 '+snapshot['sha256'][:16])

    def populate(self,value):
        if not value.get('halfpi_calibration'):raise ValueError('Rabi 보정 Ramsey 전용 설정 파일을 선택하세요.')
        config.validate(value);self.set_source(value['halfpi_calibration']);super().populate(value);self.controls()

    def controls(self,*_):
        super().controls()
        if not self.auto_ready:return
        self.source_group.setEnabled(not self.runner.running())
        error='';single_error=''
        try:
            if self.halfpi_source is None:raise ValueError('위상별 Rabi 결과 JSON을 먼저 선택하세요.')
            c={k:self.fields[k].value() for k in ('scan_start_deg','scan_stop_deg','scan_step_deg')}
            plan=config.scan_points(c);signature=(self.halfpi_source['sha256'],*c.values())
            if signature!=self.preview_signature:
                self.halfpi_table.setRowCount(len(plan));self.preview_error=''
                for row,p in enumerate(plan):
                    try:
                        point=halfpi.apply(p,self.halfpi_source)
                        values=[p['requested_angle_deg'],p['code'],point['half_pi_first_us'],point['half_pi_second_us'],'유효']
                    except ValueError as exc:
                        self.preview_error=self.preview_error or str(exc);values=[p['requested_angle_deg'],p['code'],'—','—',str(exc)]
                    for col,v in enumerate(values):self.halfpi_table.setItem(row,col,W.QTableWidgetItem(str(v)))
                self.halfpi_figure.clear();ax=self.halfpi_figure.add_subplot(111);table=halfpi.knots(self.halfpi_source)
                ax.plot([c for c,t in table],[float('nan') if t is None else t for c,t in table],'o-',markersize=3)
                ax.set(xlabel='Actual phase-shifter code',ylabel='Half-pi time (µs)',title='Rabi-derived pulse time');ax.grid(alpha=.2)
                self.halfpi_canvas.draw_idle();self.preview_signature=signature
            error=self.preview_error
        except (ValueError,KeyError) as exc:error=str(exc)
        try:
            if self.halfpi_source is None:raise ValueError('Rabi 데이터 미선택')
            p=halfpi.apply(config.phase_point(self.fields['phase_angle_deg'].value()),self.halfpi_source)
            self.angle_summary.setText(f'선형 code {p["code"]} · 첫 π/2 {p["half_pi_first_us"]:.2f} µs · 두 번째 π/2 {p["half_pi_second_us"]:.2f} µs')
        except (ValueError,KeyError) as exc:single_error=str(exc);self.angle_summary.setText(single_error)
        if error:self.start_button.setEnabled(False);self.readiness.setText(error)
        if single_error:self.single_button.setEnabled(False)
