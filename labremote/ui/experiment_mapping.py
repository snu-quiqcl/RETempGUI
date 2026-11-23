"""One nickname-only mapping table for standalone experiments and Queue."""
from copy import deepcopy
from types import SimpleNamespace
from PyQt5 import QtCore, QtWidgets as W
from labremote.devices.fpga import routing
from labremote.devices.fpga.mapping import PINS, capability
from .pin_selector import PinSelector

class MappingEditor(W.QGroupBox):
    changed=QtCore.pyqtSignal()
    def __init__(self,worker,experiment,c=None,mode=None,parent=None):
        super().__init__('이 실험의 FPGA 역할 매핑',parent)
        self.worker,self.experiment,self.mode=worker,experiment,mode
        self._settings={};self.choices={};self._loading=False
        root=W.QVBoxLayout(self)
        self.options=W.QHBoxLayout();root.addLayout(self.options)
        self.optional={}
        for role,path in ([('PMT2',('mapping','pmt_2'))] if experiment=='ion_check' else
                          [('AUX1',('roles','AUX1')),('AUX2',('roles','AUX2'))] if experiment=='decay' else []):
            box=W.QCheckBox(role+' 사용');box.setProperty('persistInput',False)
            self.optional[role]=(box,path);self.options.addWidget(box)
            box.toggled.connect(lambda enabled,role=role:self.option_changed(role,enabled))
        self.table=W.QTableWidget(0,5)
        self.table.setProperty('persistInput',False)
        self.table.setHorizontalHeaderLabels(['시퀀서 역할','UI 닉네임','물리 핀','기능','사용 단계'])
        self.table.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        for i in range(5):self.table.horizontalHeader().setSectionResizeMode(i,W.QHeaderView.Stretch if i==1 else W.QHeaderView.ResizeToContents)
        root.addWidget(self.table)
        note=W.QLabel('물리 핀은 FPGA 공통 설정에서 관리합니다. 이 표는 역할과 UI 닉네임의 연결만 저장합니다.')
        note.setWordWrap(True);root.addWidget(note)
        if c is not None:self.set_settings(c)

    def option_changed(self,role,enabled):
        if self._loading:return
        c=self.apply(self._settings);path=self.optional[role][1]
        if not enabled:routing.put(c,path,None)
        self.set_settings(c,options={role:enabled});self.changed.emit()

    def set_settings(self,c,*,mode=None,options=None):
        if mode is not None:self.mode=mode
        self._loading=True
        try:
            self._settings=routing.normalize(c,self.experiment,self.mode,self.worker.profile)
            for role,(box,path) in self.optional.items():
                with QtCore.QSignalBlocker(box):box.setChecked((options or {}).get(role,bool(routing.get(c,path))))
            selected=routing.routes(self.experiment,self._settings,self.mode)
            for r in routing.routes(self.experiment,self._settings,self.mode,all_fields=True):
                if r.role in self.optional and self.optional[r.role][0].isChecked() and r.path not in [x.path for x in selected]:selected.append(r)
            self.choices={};self.table.setRowCount(0)
            for spec in selected:
                row=self.table.rowCount();self.table.insertRow(row)
                box=PinSelector(self.worker,self.experiment,input_pin='output' not in spec.feature,
                                feature=spec.feature,raw_names=self.experiment in ('phase_shifter','scan'))
                box.setProperty('persistInput',False)
                box.setCurrentText(routing.get(self._settings,spec.path))
                self.choices[spec.path]=box;self.table.setCellWidget(row,1,box)
                for col,text in [(0,spec.role),(2,''),(3,''),(4,spec.use)]:self.table.setItem(row,col,W.QTableWidgetItem(text))
                def update(*_,box=box,row=row):
                    pin=box.currentData()
                    self.table.item(row,2).setText(pin if pin in PINS else '미지정')
                    self.table.item(row,3).setText(capability(pin) if pin in PINS else '')
                    if not self._loading:self.changed.emit()
                box.routeChanged.connect(update);update()
            self.table.setMinimumHeight(min(500,max(100,self.table.rowCount()*34+36)))
        finally:self._loading=False

    def apply(self,c):
        result=deepcopy(c)
        # Inactive selections survive a mode/option change but are not validated.
        for spec in routing.routes(self.experiment,self._settings,self.mode,all_fields=True):
            routing.put(result,spec.path,routing.get(self._settings,spec.path))
        for path,box in self.choices.items():routing.put(result,path,box.route())
        for role,(box,path) in self.optional.items():
            if not box.isChecked():routing.put(result,path,None)
        return result

    def validate(self,c):
        routing.validate(self.apply(c),self.experiment,self.mode)
