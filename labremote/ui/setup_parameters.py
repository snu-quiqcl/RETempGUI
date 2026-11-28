"""Offline editor: selected device profiles and execution bounds, without I/O."""
from copy import deepcopy
import json
from PyQt5 import QtCore,QtWidgets
from labremote.runtime.setup_workflow import catalogue,validate
from labremote.configuration.device_config import operation_config


class SetupParameters(QtWidgets.QWidget):
    changed=QtCore.pyqtSignal()

    def __init__(self,bindings_provider=None,*,profiles=None):
        super().__init__();self.bindings_provider=bindings_provider or (lambda:{})
        from .widgets.input_wheel import install_input_wheel_guard
        install_input_wheel_guard()
        self._rendering=False
        self.setProperty('persistInput',False)
        self.rows=[];self.available=[];self.workers={};self.catalogs={}
        self._saved_profiles=deepcopy(profiles or {})
        self.profiles_provider=lambda:self._saved_profiles
        self.device_note=''
        layout=QtWidgets.QVBoxLayout(self);bar=QtWidgets.QHBoxLayout();layout.addLayout(bar)
        self.add_button=QtWidgets.QPushButton('설정 추가');bar.addWidget(self.add_button);self.add_button.clicked.connect(self.add_row)
        for title,callback in [('삭제',self.remove),('위',lambda:self.move(-1)),('아래',lambda:self.move(1)),('연결 장비 새로고침',self.refresh_devices)]:
            b=QtWidgets.QPushButton(title);b.clicked.connect(callback);bar.addWidget(b)
            if title in ('위','아래'):b.setToolTip('선택한 설정 행 전체를 '+title+'로 이동합니다. 장비·출력·설정값은 함께 이동합니다.')
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

    def profile_documents(self):
        from labremote.devices.fpga.mapping import Profile
        documents={name:w.profile.document() for (family,name),w in self.workers.items()
                   if family=='fpga' and isinstance(getattr(w,'profile',None),Profile)}
        # A Queue snapshot wins over the currently connected board configuration.
        documents.update(deepcopy(self.profiles_provider() or {}))
        return documents

    def options(self,family,device=''):
        document=self.profile_documents().get(device) if family=='fpga' else None
        key=(family,device,json.dumps(document,sort_keys=True))
        if key not in self.catalogs:self.catalogs[key]=catalogue(family,device,profile=document)
        return self.catalogs[key]

    def refresh_devices(self,*_):
        self.workers={};warnings=[]
        try:
            for key,binding in self.bindings_provider().items():
                try:
                    family,bridge=binding;w=bridge.worker
                    connected=w.available if family=='ccd' else w.ps is not None
                    if connected and not w.connection_error and not w._closing and w.name:self.workers[family,w.name]=w
                except Exception as exc:warnings.append(f'{key}: {exc}')
        except Exception as exc:warnings.append(str(exc))
        self.available=sorted(self.workers)
        self.device_note='일부 장비 목록 확인: '+'; '.join(warnings) if warnings else '' if self.available else '현재 GUI에 연결된 장비가 없습니다.'
        self.render()

    def populate(self,parameters):
        p=validate(parameters,allow_empty=True,check_settings=False)
        self.rows=deepcopy(p['steps']);self.settle.setValue(p['settle_s']);self.render()

    def parameters(self,base,validate=True):
        p=dict(schema_version=1,steps=deepcopy(self.rows),settle_s=self.settle.value())
        if validate:
            from labremote.runtime.setup_workflow import validate as check
            check(p,profiles=self.profile_documents())
        return p

    def add_row(self,*_):
        self.rows.append(dict(family='',device='',parameter='',value=None));self.render(len(self.rows)-1)
        self.table.scrollToItem(self.table.item(len(self.rows)-1,0))

    def remove(self):
        row=self.table.currentRow()
        if 0<=row<len(self.rows):
            self.rows.pop(row);self.render(min(row,len(self.rows)-1));self.changed.emit()

    def move(self,offset):
        row=self.table.currentRow();other=row+offset
        if 0<=row<len(self.rows) and 0<=other<len(self.rows):
            self.rows[row],self.rows[other]=self.rows[other],self.rows[row];self.render(other)
            self.table.scrollToItem(self.table.item(other,0))

    def change_device(self,row,key):
        key=key or ('','')
        if key==(self.rows[row]['family'],self.rows[row]['device']):return
        self.rows[row].update(family=key[0],device=key[1],parameter='',value=None)
        self.render(row);self.changed.emit()

    def change_parameter(self,row,path):
        if path==self.rows[row]['parameter']:return
        if not path:
            self.rows[row].update(parameter='',value=None);self.render(row);return
        spec=self.options(self.rows[row]['family'],self.rows[row]['device'])[path].spec
        value=spec.choices[0] if spec.choices else False if spec.kind=='bool' else max(0,spec.minimum or 0)
        if not spec.choices and spec.kind!='bool' and spec.maximum is not None:value=min(value,spec.maximum)
        if spec.kind=='int':value=int(value)
        self.rows[row].update(parameter=path,value=value);self.render(row)

    def change_value(self,row,value):
        self.rows[row]['value']=value
        self.table.selectRow(row)
        self.update_status()

    def update_status(self):
        notes=[self.device_note] if self.device_note else []
        for i,row in enumerate(self.rows):
            if not row['family']:continue
            options=self.options(row['family'],row['device'])
            if not options:
                notes.append(row['device']+(': FPGA 공통 핀 설정을 불러오세요.' if row['family']=='fpga' else ': 이 장비에는 범용 Setup에 연결된 설정 항목이 없습니다. 전용 장비 탭을 사용하세요.'))
            setting=options.get(row['parameter'])
            if row['parameter'] and setting is None:
                notes.append(f"{row['device']}: 저장된 출력/파라미터를 현재 설정에서 찾을 수 없습니다: {row['parameter']}")
            if setting:
                problem=''
                try:setting.spec.validate(row['value'],request=True)
                except Exception as exc:problem=str(exc);notes.append(f"{row['device']} / {row['parameter']}: {problem}")
                field=self.table.cellWidget(i,3)
                if field is not None:
                    field.setStyleSheet('color: #b42318' if problem else '')
                    field.setToolTip(f'허용 범위: {setting.spec.minimum} .. {setting.spec.maximum} {setting.spec.unit}'+('\n'+problem if problem else ''))
        self.info.setText('\n'.join(dict.fromkeys(notes)) if notes else '장비 선택 → 파라미터 선택 → 값 설정. 연결 해제된 기존 선택은 유지됩니다.')

    def refresh_profiles(self,*_):
        self.render(self.table.currentRow())

    def eventFilter(self,watched,event):
        if event.type() in (QtCore.QEvent.FocusIn,QtCore.QEvent.MouseButtonPress) and not self._rendering:
            row=watched.property('setupRow')
            if row is not None and 0<=row<len(self.rows):self.table.selectRow(row)
        return super().eventFilter(watched,event)

    def _field(self,row,column,kind):
        field=self.table.cellWidget(row,column)
        if isinstance(field,kind):return field
        # Discarded controls may still have queued events until Qt deletes them.
        # Callbacks below accept only the control currently installed in this cell.
        field=kind();field.setProperty('setupRow',row);field.installEventFilter(self)
        if isinstance(field,QtWidgets.QAbstractSpinBox):
            field.lineEdit().setProperty('setupRow',row);field.lineEdit().installEventFilter(self)
            field.setKeyboardTracking(False)
            field.valueChanged.connect(lambda value,i=row,b=field:self._value_changed(i,b,value))
        else:
            field.currentIndexChanged.connect(lambda _,i=row,c=column,b=field:self._choice_changed(i,c,b))
        self.table.setCellWidget(row,column,field)
        return field

    def _choice_changed(self,row,column,field):
        if self._rendering or row>=len(self.rows) or self.table.cellWidget(row,column) is not field:return
        self.table.selectRow(row)
        value=field.currentData()
        if column==1:self.change_device(row,value)
        elif column==2:self.change_parameter(row,value)
        else:self.change_value(row,value)

    def _value_changed(self,row,field,value):
        if self._rendering or row>=len(self.rows) or self.table.cellWidget(row,3) is not field:return
        if field.property('integerValue'):value=int(value)
        self.change_value(row,value)

    @staticmethod
    def _fill_combo(field,entries,selected):
        with QtCore.QSignalBlocker(field):
            old=[(field.itemText(i),field.itemData(i)) for i in range(field.count())]
            if old!=entries:
                field.clear()
                for label,value in entries:field.addItem(label,value)
            # Qt's findData does not reliably compare Python tuple identities.
            field.setCurrentIndex(next((i for i in range(field.count()) if field.itemData(i)==selected),-1))

    def render(self,select=None):
        if self._rendering:return
        if select is None:select=self.table.currentRow()
        bars=(self.table.verticalScrollBar(),self.table.horizontalScrollBar())
        positions=[bar.value() for bar in bars]
        self.catalogs={};self._rendering=True
        try:
            with operation_config():self._render_rows(select)
        except Exception as exc:self.info.setText('Setup 설정 확인: '+str(exc))
        finally:
            self._rendering=False
            for bar,position in zip(bars,positions):bar.setValue(position)

    def _render_rows(self,select):
        # Keep controls alive when values, profiles or row order change.
        self.table.setRowCount(len(self.rows))
        for i,row in enumerate(self.rows):
            self.table.setItem(i,0,QtWidgets.QTableWidgetItem(str(i+1)))
            key=(row['family'],row['device'])
            device=self._field(i,1,QtWidgets.QComboBox)
            entries=[('장비 선택…',None)]+[(f'{n} ({f})',(f,n)) for f,n in self.available]
            if row['device'] and key not in self.available:entries.append((row['device']+' · 연결 안 됨',key))
            self._fill_combo(device,entries,key if row['device'] else None)
            param=self._field(i,2,QtWidgets.QComboBox)
            options=self.options(*key) if row['family'] else {}
            entries=[('파라미터 선택…','')]
            for path,setting in options.items():
                title=path.removeprefix('outputs.')+(f' [{setting.pin}]' if setting.pin else '')
                entries.append((title,path))
            if row['parameter'] and row['parameter'] not in options:
                entries.append((row['parameter']+' · 확인 필요',row['parameter']))
            self._fill_combo(param,entries,row['parameter']);param.setEnabled(bool(options))
            setting=options.get(row['parameter'])
            if setting:
                spec=setting.spec
                if spec.kind=='bool' or spec.choices:
                    field=self._field(i,3,QtWidgets.QComboBox);entries=[]
                    for value in (spec.choices or (False,True)):
                        label=('ON' if value else 'OFF') if spec.kind=='bool' else f'Position {value}' if row['family']=='flip' else str(value)
                        entries.append((label,value))
                    self._fill_combo(field,entries,row['value'])
                else:
                    field=self._field(i,3,QtWidgets.QDoubleSpinBox)
                    with QtCore.QSignalBlocker(field):
                        field.setProperty('integerValue',spec.kind=='int')
                        field.setDecimals(0 if spec.kind=='int' else 9)
                        lo=spec.minimum if spec.minimum is not None else -1e100
                        hi=spec.maximum if spec.maximum is not None else 1e100
                        value=row['value'] if type(row['value']) in (int,float) else 0
                        # Display an invalid saved value faithfully; never silently clamp it.
                        field.setRange(min(lo,value),max(hi,value));field.setValue(value)
                field.show();self.table.setItem(i,4,QtWidgets.QTableWidgetItem(spec.unit or '—'))
            else:
                field=self.table.cellWidget(i,3)
                if field is not None:field.hide()
                self.table.setItem(i,4,QtWidgets.QTableWidgetItem(''))
        self.update_status()
        if select is not None and 0<=select<len(self.rows):self.table.selectRow(select)
