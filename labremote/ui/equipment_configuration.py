"""Table-based editor for equipment membership, not hardware parameters."""
from PyQt5 import QtCore,QtWidgets
from labremote.config.equipment import GROUPS,FAMILY_GROUP,validate

class EquipmentConfigurationDialog(QtWidgets.QDialog):
    def __init__(self,document,candidates,parent=None):
        super().__init__(parent);self.setWindowTitle('Configuration · 사용할 장비');self.resize(850,640)
        layout=QtWidgets.QVBoxLayout(self)
        self.name=QtWidgets.QLineEdit(document['name']);layout.addWidget(self.name)
        note=QtWidgets.QLabel('체크된 장비만 그룹 연결 대상에 포함합니다. 장비별 상세 설정은 변경하지 않습니다.\n수동으로 연결한 장비는 기존처럼 workflow에서 사용할 수 있습니다. 저장/적용만으로 장비가 연결되거나 출력이 켜지지 않습니다.')
        note.setWordWrap(True);layout.addWidget(note)
        self.table=QtWidgets.QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['사용','종류','장비 이름','그룹']);self.table.setColumnWidth(0,60);self.table.setColumnWidth(1,150);self.table.setColumnWidth(3,140);self.table.horizontalHeader().setSectionResizeMode(2,QtWidgets.QHeaderView.Stretch);layout.addWidget(self.table)
        for entry in document['devices']:self.add_entry(entry)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        self.candidates=QtWidgets.QComboBox()
        for item in candidates:self.candidates.addItem(item['family']+' / '+item['name'],item)
        row.addWidget(self.candidates,1)
        add=QtWidgets.QPushButton('조회 장비 추가');row.addWidget(add)
        add.clicked.connect(lambda:self.add_entry(self.candidates.currentData()) if self.candidates.currentData() else None)
        blank=QtWidgets.QPushButton('직접 추가');row.addWidget(blank);blank.clicked.connect(lambda:self.add_entry(dict(family='windfreak',name='',group='RF',enabled=False)))
        remove=QtWidgets.QPushButton('선택 행 삭제');row.addWidget(remove);remove.clicked.connect(lambda:self.table.removeRow(self.table.currentRow()))
        self.error=QtWidgets.QLabel();self.error.setWordWrap(True);layout.addWidget(self.error)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('구성 적용');buttons.accepted.connect(self.accept_config);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
    def add_entry(self,item):
        row=self.table.rowCount();self.table.insertRow(row)
        check=QtWidgets.QTableWidgetItem();check.setFlags(QtCore.Qt.ItemIsEnabled|QtCore.Qt.ItemIsUserCheckable);check.setCheckState(QtCore.Qt.Checked if item['enabled'] else QtCore.Qt.Unchecked);self.table.setItem(row,0,check)
        family=QtWidgets.QComboBox();family.addItems(list(FAMILY_GROUP));family.setCurrentText(item['family']);self.table.setCellWidget(row,1,family)
        self.table.setItem(row,2,QtWidgets.QTableWidgetItem(item['name']))
        group=QtWidgets.QComboBox();group.addItems(GROUPS);group.setCurrentText(item['group']);self.table.setCellWidget(row,3,group)
    def document(self):
        return validate(dict(schema_version=1,name=self.name.text().strip(),devices=[dict(family=self.table.cellWidget(r,1).currentText(),name=self.table.item(r,2).text().strip(),group=self.table.cellWidget(r,3).currentText(),enabled=self.table.item(r,0).checkState()==QtCore.Qt.Checked) for r in range(self.table.rowCount())]))
    def accept_config(self):
        try:self.document()
        except Exception as exc:self.error.setText(str(exc));return
        self.accept()
