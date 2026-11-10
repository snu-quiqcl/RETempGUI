"""Board aliases and explicit experiment-role routing; no hardware I/O."""
import json
from PyQt5 import QtCore, QtWidgets as W
from labremote.devices.fpga.mapping import PINS, DEFAULT_ROLES, Profile, capability, compatible

ROLES = {
    'fluorescence': ('PMTA','PMTC','PMTFA','PMTFC','AOMA','AOMC'),
    'micromotion': ('SYNC','PMTA','PMTC','PMTFA','PMTFC'),
}


class RoleMapping(W.QGroupBox):
    def __init__(self, worker, experiment, parent=None):
        super().__init__('실험 신호 → FPGA 핀 이름', parent)
        self.worker, self.experiment = worker, experiment
        self.setCheckable(True); self.setChecked(False)
        outer = W.QVBoxLayout(self)
        self.body = W.QWidget(); outer.addWidget(self.body)
        form = W.QFormLayout(self.body)
        self.choices = {}
        for role in ROLES.get(experiment, tuple(DEFAULT_ROLES)):
            combo = W.QComboBox(); combo.setProperty('persistInput', False)
            self.choices[role] = combo; form.addRow(role, combo)
        buttons = W.QHBoxLayout()
        apply = W.QPushButton('이 FPGA의 실험 매핑 저장'); apply.clicked.connect(self.apply)
        reload = W.QPushButton('현재 매핑 다시 읽기'); reload.clicked.connect(self.refresh)
        buttons.addWidget(apply); buttons.addWidget(reload); form.addRow(buttons)
        self.status = W.QLabel(); self.status.setWordWrap(True); form.addRow(self.status)
        self.toggled.connect(self.body.setVisible); self.body.hide(); self.refresh()

    def refresh(self):
        document = self.worker.profile.document()
        mapping = {**DEFAULT_ROLES, **document['experiments'].get(self.experiment, {})}
        for role, combo in self.choices.items():
            combo.clear()
            for pin, name in document['pins'].items():
                if compatible(self.experiment, role, pin):
                    combo.addItem(f'{name} [{pin}]', pin)
            combo.setCurrentIndex(combo.findData(mapping[role]))
        self.status.setText(document['alias'] + ' · ' + document['device_id'] + '\n기존 실험의 역할 이름을 유지하며, 이 표에서 실제 FPGA 핀을 선택합니다. 실행 중 매핑은 변경할 수 없습니다.')

    def apply(self):
        try:
            document = self.worker.profile.document()
            roles = dict(document['experiments'].get(self.experiment, {}))
            roles.update({role: box.currentData() for role, box in self.choices.items()})
            # Active-role collisions are validated by each experiment; unused
            # logical roles may legitimately point to a currently selected pin.
            document['experiments'][self.experiment] = roles
            self.worker.update_profile(Profile(document)); self.refresh()
            self.status.setText('저장 완료 · 다음 실행부터 적용')
        except Exception as exc:
            self.status.setText(str(exc))


class BoardMapping(W.QDialog):
    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self.worker = worker; self.document = worker.profile.document()
        self.setWindowTitle('FPGA Configuration · ' + self.document['device_id']); self.resize(650,750)
        root = W.QVBoxLayout(self)
        root.addWidget(W.QLabel('신호 ID와 펌웨어 기능은 고정입니다. 별명과 핀 이름만 수정합니다.'))
        form = W.QFormLayout(); root.addLayout(form)
        self.alias = W.QLineEdit(self.document['alias']); form.addRow('저장 데이터 별명', self.alias)
        self.table = W.QTableWidget(len(PINS),3)
        self.table.setHorizontalHeaderLabels(['신호 ID','펌웨어 기능','FPGA 핀 이름'])
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.Stretch); root.addWidget(self.table)
        self.populate()
        row = W.QHBoxLayout(); root.addLayout(row)
        for title, fn in [('Configuration 불러오기',self.load),('다른 이름으로 저장',self.export),('적용 / 로컬 저장',self.apply)]:
            button=W.QPushButton(title); button.clicked.connect(fn); row.addWidget(button)
        self.status=W.QLabel(); self.status.setWordWrap(True); root.addWidget(self.status)

    def populate(self):
        self.alias.setText(self.document['alias'])
        for row,pin in enumerate(PINS):
            for column,text in enumerate((pin,capability(pin),self.document['pins'][pin])):
                item=W.QTableWidgetItem(text)
                if column<2:item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.table.setItem(row,column,item)

    def value(self):
        document=dict(self.document)
        document['alias']=self.alias.text().strip()
        document['pins']={pin:self.table.item(row,2).text().strip() for row,pin in enumerate(PINS)}
        return Profile(document)

    def load(self):
        path,_=W.QFileDialog.getOpenFileName(self,'Load FPGA Configuration','','JSON (*.json)')
        if not path:return
        try:
            from pathlib import Path
            document=json.loads(Path(path).read_text(encoding='utf-8-sig'))
            document['device_id']=self.worker.profile.device_id
            document['alias']=self.alias.text().strip()
            self.document=Profile(document).document();self.populate()
        except Exception as exc:self.status.setText(str(exc))

    def export(self):
        try:
            profile=self.value()
            path,_=W.QFileDialog.getSaveFileName(self,'Save FPGA Configuration','fpga.local.json','Local JSON (*.local.json)')
            if path:
                from pathlib import Path
                if not path.endswith('.local.json'):path += '.local.json'
                Path(path).write_text(json.dumps(profile.document(),ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception as exc:self.status.setText(str(exc))

    def apply(self):
        try:
            self.worker.update_profile(self.value());self.accept()
        except Exception as exc:self.status.setText(str(exc))


class LocalFPGADialog(W.QDialog):
    def __init__(self, owner):
        super().__init__(owner);self.owner=owner;self.ports=[];self.fallback={}
        self.setWindowTitle('로컬 FPGA 검색 / 연결');self.resize(700,220)
        root=W.QVBoxLayout(self);self.choices=W.QComboBox();root.addWidget(self.choices)
        self.alias=W.QLineEdit();self.alias.setPlaceholderText('저장 데이터 별명 (새 장비 연결 시 필수)');root.addWidget(self.alias)
        row=W.QHBoxLayout();root.addLayout(row)
        scan=W.QPushButton('USB / COM 검색');connect=W.QPushButton('연결 / FPGA 창 열기')
        row.addWidget(scan);row.addWidget(connect)
        self.status=W.QLabel('검색은 포트를 열지 않습니다. FPGA 여부는 연결 시 버전을 확인합니다.');self.status.setWordWrap(True);root.addWidget(self.status)
        from labremote.devices.fpga.ports import PortScanner
        self.scanner=PortScanner(self);self.scanner.found.connect(self.found);self.scanner.failed.connect(self.status.setText)
        scan.clicked.connect(lambda:self.scanner.start() if not self.scanner.isRunning() else None)
        connect.clicked.connect(self.connect_device);self.scanner.start()

    def found(self, ports):
        self.ports=ports;self.choices.clear()
        for port in ports:
            self.choices.addItem(f"{port['device']} · {port['description']} · USB serial: {port.get('serial_number') or '없음 (순차 번호)'}",port)

    def connect_device(self):
        try:
            info=self.choices.currentData()
            if info is None:raise ValueError('포트를 먼저 선택하세요.')
            for name,panel in self.owner.family_tabs['fpga'].items():
                if getattr(panel.worker,'_claimed_port',None)==info['device']:
                    self.owner.open_device_control('fpga',name);return
            from labremote.devices.fpga.registry import identify
            if not self.alias.text().strip():
                # Existing serial registrations retain their saved alias.
                from labremote.devices.fpga.registry import read
                serial=info.get('serial_number')
                if not serial or not any(e.get('usb_identity')==[info.get('vid'),info.get('pid'),serial] for e in read()['devices'].values()):
                    raise ValueError('새 FPGA의 저장 데이터 별명을 입력하세요.')
            key=info['device']
            if key in self.fallback:name,stable=self.fallback[key],False
            else:
                name,stable=identify(info,self.ports,self.alias.text().strip())
                if not stable:self.fallback[key]=name
            if name not in self.owner.family_tabs['fpga']:
                self.owner.register_equipment('fpga',name)
            panel=self.owner.family_tabs['fpga'][name]
            panel.serial.setText(info['device']);panel._serial_ports=self.ports
            self.owner.open_device_control('fpga',name)
            if not panel.connected:panel._connect()
            self.status.setText(name + (' · USB 식별 저장됨' if stable else ' · 임시 순차 식별: 재시작 후 실물 연결을 확인하세요.'))
        except Exception as exc:self.status.setText(str(exc))

    def closeEvent(self,event):
        if self.scanner.isRunning():event.ignore();return
        event.accept()
