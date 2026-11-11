"""One permanent connection page; successful connections reveal device tabs."""
from PyQt5 import QtCore,QtWidgets as W
from labremote.devices.fpga.ports import PortScanner
from labremote.devices.fpga.registry import identify,read


class FPGAConnections(W.QWidget):
    def __init__(self,owner):
        super().__init__();self.owner=owner;self.ports=[];self.fallback={};self.pending=None
        root=W.QVBoxLayout(self)
        row=W.QHBoxLayout();root.addLayout(row);row.addWidget(W.QLabel('로컬 FPGA 연결'),1)
        self.scan=W.QPushButton('USB 다시 검색');row.addWidget(self.scan)
        self.table=W.QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['포트','USB Serial','별명 / 인스턴스','상태','동작'])
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.Stretch)
        self.table.setEditTriggers(W.QAbstractItemView.NoEditTriggers);self.table.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        root.addWidget(self.table)
        form=W.QFormLayout();root.addLayout(form)
        self.port=W.QLabel('장비를 선택하세요.');form.addRow('선택한 포트',self.port)
        self.alias=W.QLineEdit();self.alias.setPlaceholderText('저장 데이터 별명');self.alias.setProperty('persistInput',False);form.addRow('저장 별명',self.alias)
        self.connect_button=W.QPushButton('연결하고 인스턴스 열기');form.addRow(self.connect_button)
        self.status=W.QLabel('FPGA는 여기에서 개별 연결합니다. 전체 연결에 포함되지 않습니다.');self.status.setWordWrap(True);root.addWidget(self.status);root.addStretch()
        self.scanner=PortScanner(self);self.scanner.found.connect(self.found);self.scanner.failed.connect(self.status.setText)
        self.scan.clicked.connect(self.search);self.connect_button.clicked.connect(self.connect_device)
        self.table.currentCellChanged.connect(self.selection)
        self.timer=QtCore.QTimer(self);self.timer.setInterval(200);self.timer.timeout.connect(self.poll);self.timer.start()

    def search(self):
        if not self.scanner.isRunning():self.scanner.start()
    def found(self,ports):
        self.ports=ports;self.table.setRowCount(len(ports));self.paint_rows()
    def paint_rows(self):
        for row,p in enumerate(self.ports):
            panel=next((v for v in self.owner.family_tabs['fpga'].values() if getattr(v.worker,'_claimed_port',None)==p['device']),None)
            values=(p['device'],p.get('serial_number') or '없음',panel.worker.profile.alias+' · '+panel.name if panel else '—','연결됨' if panel and panel.connected else '미연결','탭 열기' if panel and panel.connected else '선택')
            for col,value in enumerate(values):self.table.setItem(row,col,W.QTableWidgetItem(value))
    def selection(self,*_):
        row=self.table.currentRow()
        if 0<=row<len(self.ports):self.port.setText(self.ports[row]['device'])
    def connect_device(self):
        if self.pending is not None:return
        try:
            row=self.table.currentRow()
            if not 0<=row<len(self.ports):raise ValueError('USB 장비를 선택하세요.')
            info=self.ports[row]
            for name,panel in self.owner.family_tabs['fpga'].items():
                if panel.connected and getattr(panel.worker,'_claimed_port',None)==info['device']:
                    self.owner.open_device_control('fpga',name);return
            serial=info.get('serial_number');saved=read()['devices']
            known=bool(serial) and sum(p.get('serial_number')==serial for p in self.ports)==1 and any(e.get('usb_identity')==[info.get('vid'),info.get('pid'),serial] for e in saved.values())
            if not known and info['device'] not in self.fallback and not self.alias.text().strip():raise ValueError('새 장비의 저장 별명을 입력하세요.')
            if info['device'] in self.fallback:name=self.fallback[info['device']]
            else:
                name,stable=identify(info,self.ports,self.alias.text().strip())
                if not stable:self.fallback[info['device']]=name
            if name not in self.owner.family_tabs['fpga']:
                self.owner._add_family('fpga',name)
            panel=self.owner.family_tabs['fpga'][name]
            panel.serial.setText(info['device']);panel._serial_ports=self.ports
            handle=panel._connect()
            if handle is None:raise RuntimeError(panel.message.text())
            self.pending=(name,handle);self.status.setText(name+' 연결 중…');self.connect_button.setEnabled(False)
        except Exception as exc:self.status.setText(str(exc))
    def poll(self):
        if self.pending is None:return
        name,handle=self.pending
        if not handle.done.is_set():return
        self.pending=None;self.connect_button.setEnabled(True)
        if handle.error:self.status.setText('연결 실패: '+str(handle.error))
        else:
            panel=self.owner.family_tabs['fpga'][name];tabs=self.owner.family_subtabs['fpga']
            if tabs.indexOf(panel)<0:tabs.addTab(panel,panel.worker.profile.alias+' · '+name)
            self.owner.open_device_control('fpga',name);self.status.setText('연결 완료 · '+name)
        self.paint_rows()
    def shutdown(self):self.timer.stop()
    def still_running(self):return self.scanner.isRunning()
