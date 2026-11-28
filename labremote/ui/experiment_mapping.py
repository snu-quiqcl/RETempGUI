"""One nickname-only mapping table for standalone experiments and Queue."""
from copy import deepcopy
from PyQt5 import QtCore, QtWidgets as W
from labremote.devices.fpga import routing
from labremote.devices.fpga.mapping import PINS, capability
from .pin_selector import PinSelector

class MappingEditor(W.QGroupBox):
    """Own one selector per route until this editor is destroyed.

    Experiment views may retain selectors in roles/channel/phase lists. Reloads
    update those same objects; optional routes hide their rows instead of
    destroying widgets. ``choices`` contains only currently active routes.
    """
    changed=QtCore.pyqtSignal()
    def __init__(self,worker,experiment,c=None,mode=None,parent=None):
        super().__init__('이 실험의 FPGA 역할 매핑',parent)
        self.worker,self.experiment,self.mode=worker,experiment,mode
        self._settings={};self.choices={};self._loading=False
        self._selectors={};self._rows={}
        root=W.QVBoxLayout(self)
        self.options=W.QHBoxLayout();root.addLayout(self.options)
        self.optional={}
        if experiment in ('rabi','spam'):
            self.detector_count=W.QComboBox()
            self.detector_count.addItem('PMT 1개',1);self.detector_count.addItem('PMT 2개',2)
            self.detector_count.setProperty('persistInput',False)
            self.options.addWidget(W.QLabel('검출기'));self.options.addWidget(self.detector_count)
            self.detector_count.currentIndexChanged.connect(self.detectors_changed)
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

    def detectors_changed(self):
        if self._loading:return
        c=self.apply(self._settings)
        routing.put(c,('roles','PMT2'),self._selectors[('roles','PMT2')].route())
        self.set_settings(c);self.changed.emit()

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
            if self.experiment in ('rabi','spam'):
                with QtCore.QSignalBlocker(self.detector_count):
                    self.detector_count.setCurrentIndex(self.detector_count.findData(c.get('detector_count',1)))
            for role,(box,path) in self.optional.items():
                with QtCore.QSignalBlocker(box):box.setChecked((options or {}).get(role,bool(routing.get(c,path))))
            specs=routing.routes(self.experiment,self._settings,self.mode,all_fields=True)
            selected=routing.routes(self.experiment,self._settings,self.mode)
            for r in specs:
                if r.role in self.optional and self.optional[r.role][0].isChecked() and r.path not in [x.path for x in selected]:selected.append(r)
            for spec in specs:
                box=self._selectors.get(spec.path)
                if box is None:
                    row=self.table.rowCount();self.table.insertRow(row)
                    box=PinSelector(self.worker,self.experiment,input_pin='output' not in spec.feature,
                                    feature=spec.feature,raw_names=self.experiment in ('phase_shifter','scan'))
                    self._selectors[spec.path]=box;self._rows[spec.path]=row
                    self.table.setCellWidget(row,1,box)
                    for col in (0,2,3,4):self.table.setItem(row,col,W.QTableWidgetItem())
                    box.routeChanged.connect(lambda path=spec.path:self._route_changed(path))
                row=self._rows[spec.path]
                # No signals escape while a settings document is being applied.
                with QtCore.QSignalBlocker(box):
                    box.worker=self.worker
                    box.feature=spec.feature;box.input_pin='output' not in spec.feature
                    box.refresh()
                    box.setCurrentText(routing.get(self._settings,spec.path))
                self.table.item(row,0).setText('PMT1' if self.experiment in ('rabi','spam') and spec.role=='PMT' else spec.role)
                if self.experiment=='entanglement_no_mirror' and spec.role in ('PMTFA','PMTFC'):
                    self.table.item(row,0).setText('Readout PMT 1' if spec.role=='PMTFA' else 'Readout PMT 2')
                self.table.item(row,4).setText(spec.use)
                self._route_changed(spec.path)
            self.choices.clear()
            self.choices.update((spec.path,self._selectors[spec.path]) for spec in selected)
            for path,row in self._rows.items():self.table.setRowHidden(row,path not in self.choices)
            self.table.setMinimumHeight(min(500,max(100,len(selected)*34+36)))
        finally:self._loading=False

    def _route_changed(self,path):
        row=self._rows[path];pin=self._selectors[path].currentData()
        self.table.item(row,2).setText(pin if pin in PINS else '미지정')
        self.table.item(row,3).setText(capability(pin) if pin in PINS else '')
        if not self._loading and path in self.choices:self.changed.emit()

    def apply(self,c):
        result=deepcopy(c)
        # Inactive selections survive a mode/option change but are not validated.
        for spec in routing.routes(self.experiment,self._settings,self.mode,all_fields=True):
            routing.put(result,spec.path,routing.get(self._settings,spec.path))
        for path,box in self.choices.items():routing.put(result,path,box.route())
        if self.experiment in ('rabi','spam'):
            result['detector_count']=self.detector_count.currentData()
            # Keep the hidden selector alive, but an inactive PMT is never run.
            if result['detector_count']==1:routing.put(result,('roles','PMT2'),None)
        for role,(box,path) in self.optional.items():
            if not box.isChecked():routing.put(result,path,None)
        return result

    def validate(self,c):
        routing.validate(self.apply(c),self.experiment,self.mode)
