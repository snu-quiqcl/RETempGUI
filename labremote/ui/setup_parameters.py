"""Offline editor: connected bindings supply names; no hardware calls on edit."""
from copy import deepcopy
from PyQt5 import QtCore,QtWidgets
from labremote.runtime.setup_workflow import catalogue,validate


class SetupParameters(QtWidgets.QWidget):
    def __init__(self,bindings_provider=None):
        super().__init__();self.bindings_provider=bindings_provider or (lambda:{});self.rows=[];self.available=[];self.catalogs={}
        layout=QtWidgets.QVBoxLayout(self);bar=QtWidgets.QHBoxLayout();layout.addLayout(bar)
        self.add_button=QtWidgets.QPushButton('설정 추가');bar.addWidget(self.add_button);self.add_button.clicked.connect(self.add_row)
        for title,callback in [('삭제',self.remove),('위',lambda:self.move(-1)),('아래',lambda:self.move(1)),('연결 장비 새로고침',self.refresh_devices)]:
            b=QtWidgets.QPushButton(title);b.clicked.connect(callback);bar.addWidget(b)
        bar.addStretch();self.table=QtWidgets.QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['순서','장비','파라미터 / 출력','설정값','단위'])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows);self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection);self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents);self.table.horizontalHeader().setSectionResizeMode(2,QtWidgets.QHeaderView.Stretch);layout.addWidget(self.table,1)
        self.info=QtWidgets.QLabel();self.info.setWordWrap(True);layout.addWidget(self.info)
        form=QtWidgets.QFormLayout();layout.addLayout(form);self.settle=QtWidgets.QDoubleSpinBox();self.settle.setRange(0,3600);self.settle.setDecimals(2);self.settle.setValue(1);form.addRow('전체 설정 후 대기 (s)',self.settle)
        note=QtWidgets.QLabel('위에서 아래 순서로 실행하며 각 요청의 완료를 기다립니다.\n적용은 Queue 항목만 저장합니다. 장비 변경은 Queue 실행 시 수행합니다.\n실패하면 다음 설정을 중단합니다. 이미 적용한 값은 자동 복원하지 않습니다.');note.setWordWrap(True);layout.addWidget(note)
        self.refresh_devices()

    @staticmethod
    def defaults():return dict(schema_version=1,steps=[],settle_s=1.)

    def options(self,family):
        if family not in self.catalogs:self.catalogs[family]=catalogue(family)
        return self.catalogs[family]

    def refresh_devices(self):
        try:
            names=set()
            for family,bridge in self.bindings_provider().values():
                w=bridge.worker
                if w.ps is not None and not w.connection_error and not w._closing and w.name:names.add((family,w.name))
            self.available=sorted(names)
            self.info.setText('장비 선택 → 파라미터 선택 → 값 설정. 연결 해제된 기존 선택은 유지됩니다.')
        except Exception as exc:self.available=[];self.info.setText('연결 목록 확인: '+str(exc))
        self.render()

    def populate(self,parameters):
        p=validate(parameters,allow_empty=True);self.rows=deepcopy(p['steps']);self.settle.setValue(p['settle_s']);self.render()

    def parameters(self,base,validate=True):
        p=dict(schema_version=1,steps=deepcopy(self.rows),settle_s=self.settle.value())
        if validate:
            from labremote.runtime.setup_workflow import validate as check
            check(p)
        return p

    def add_row(self,*_):
        self.rows.append(dict(family='',device='',parameter='',value=None));self.render(len(self.rows)-1)

    def remove(self):
        row=self.table.currentRow()
        if 0<=row<len(self.rows):self.rows.pop(row);self.render(min(row,len(self.rows)-1))

    def move(self,offset):
        row=self.table.currentRow();other=row+offset
        if 0<=row<len(self.rows) and 0<=other<len(self.rows):self.rows[row],self.rows[other]=self.rows[other],self.rows[row];self.render(other)

    def change_device(self,row,key):
        if key is None:return
        self.rows[row].update(family=key[0],device=key[1],parameter='',value=None);self.render(row)
        if not self.options(key[0]):self.info.setText('이 장비에는 범용 Setup에 연결된 설정 항목이 없습니다. 전용 장비 탭을 사용하세요.')

    def change_parameter(self,row,path):
        if not path:return
        spec=self.options(self.rows[row]['family'])[path].spec
        value=spec.choices[0] if spec.choices else False if spec.kind=='bool' else max(0,spec.minimum or 0)
        if spec.kind=='int':value=int(value)
        self.rows[row].update(parameter=path,value=value);self.render(row)

    def render(self,select=None):
        self.table.setRowCount(0);self.table.setRowCount(len(self.rows))
        for i,row in enumerate(self.rows):
            self.table.setItem(i,0,QtWidgets.QTableWidgetItem(str(i+1)))
            device=QtWidgets.QComboBox();device.addItem('장비 선택…',None)
            key=(row['family'],row['device'])
            for f,n in self.available:device.addItem(f'{n} ({f})',(f,n))
            if row['device'] and key not in self.available:device.addItem(row['device']+' · 연결 안 됨',key)
            device.setCurrentIndex(next((n for n in range(device.count()) if device.itemData(n)==key),0));self.table.setCellWidget(i,1,device)
            device.currentIndexChanged.connect(lambda _,i=i,b=device:self.change_device(i,b.currentData()))
            param=QtWidgets.QComboBox();param.addItem('파라미터 선택…','');options=self.options(row['family']) if row['family'] else {}
            for path in options:param.addItem(path.removeprefix('outputs.'),path)
            if row['parameter'] and row['parameter'] not in options:param.addItem(row['parameter']+' · 지원 안 됨',row['parameter'])
            param.setCurrentIndex(max(0,param.findData(row['parameter'])));param.setEnabled(bool(options));self.table.setCellWidget(i,2,param)
            param.currentIndexChanged.connect(lambda _,i=i,b=param:self.change_parameter(i,b.currentData()))
            setting=options.get(row['parameter'])
            if setting:
                spec=setting.spec
                if spec.kind=='bool' or spec.choices:
                    field=QtWidgets.QComboBox()
                    for value in (spec.choices or (False,True)):
                        label=('ON' if value else 'OFF') if spec.kind=='bool' else f'Position {value}' if row['family']=='flip' else str(value)
                        field.addItem(label,value)
                    field.setCurrentIndex(field.findData(row['value']));field.currentIndexChanged.connect(lambda _,i=i,b=field:self.rows[i].update(value=b.currentData()))
                else:
                    field=QtWidgets.QDoubleSpinBox();field.setDecimals(0 if spec.kind=='int' else 9);field.setRange(-1e100,1e100);field.setKeyboardTracking(False);field.setValue(row['value'])
                    field.valueChanged.connect(lambda v,i=i,kind=spec.kind:self.rows[i].update(value=int(v) if kind=='int' else v))
                field.setToolTip(f'허용 범위: {spec.minimum} .. {spec.maximum} {spec.unit}');self.table.setCellWidget(i,3,field)
                self.table.setItem(i,4,QtWidgets.QTableWidgetItem(spec.unit or '—'))
        if select is not None and 0<=select<len(self.rows):self.table.selectRow(select)
