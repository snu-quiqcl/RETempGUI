import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
from PyQt5 import QtCore,QtWidgets
from labremote.runtime.workflow_queue import QueueRunner,freeze_job,validate_plan,read,save

class QueueThread(QtCore.QThread):
    changed=QtCore.pyqtSignal(object)
    failed=QtCore.pyqtSignal(str)
    def __init__(self,bindings,plan,directory,parent=None):
        super().__init__(parent);self.runner=QueueRunner(bindings,plan,directory,self.changed.emit)
    def run(self):
        try:self.runner.run()
        except Exception as exc:self.failed.emit(f'{type(exc).__name__}: {exc}')

class QueueTab(QtWidgets.QWidget):
    state_changed=QtCore.pyqtSignal(object)
    def __init__(self,bindings_provider,parent=None):
        super().__init__(parent);self.bindings_provider=bindings_provider;self.jobs=[];self.thread=None;self.dirty=False
        layout=QtWidgets.QVBoxLayout(self);layout.addWidget(QtWidgets.QLabel('각 작업은 독립된 main(devices) workflow입니다. 추가한 Python 소스와 JSON 변수를 사본으로 보관합니다.'))
        row=QtWidgets.QHBoxLayout();layout.addLayout(row);self.edit_buttons=[]
        for label,fn in [('Workflow 추가',self.add_file),('편집',self.edit_job),('복제',self.duplicate),('삭제',self.remove),('위',lambda:self.move(-1)),('아래',lambda:self.move(1)),('Queue 불러오기',self.load_plan),('Queue 저장',self.save_plan)]:
            b=QtWidgets.QPushButton(label);b.clicked.connect(fn);row.addWidget(b);self.edit_buttons.append(b)
        self.table=QtWidgets.QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Workflow','반복','실패 정책','파일'])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows);self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection);self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers);self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents);self.table.horizontalHeader().setStretchLastSection(True);layout.addWidget(self.table,1)
        self.table.cellDoubleClicked.connect(lambda *_:self.edit_job())
        row=QtWidgets.QHBoxLayout();layout.addLayout(row);row.addWidget(QtWidgets.QLabel('전체 목록 반복'));self.repeat=QtWidgets.QSpinBox();self.repeat.setRange(1,10000);row.addWidget(self.repeat);self.repeat.valueChanged.connect(lambda *_:setattr(self,'dirty',True))
        self.directory=QtWidgets.QLineEdit(str(Path(__file__).resolve().parents[2]/'data/queues'));row.addWidget(self.directory,1);self.folder_button=QtWidgets.QPushButton('저장 폴더');row.addWidget(self.folder_button);self.folder_button.clicked.connect(self.choose_folder)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        self.run_button=QtWidgets.QPushButton('Queue 실행');self.pause_button=QtWidgets.QPushButton('현재 작업 후 일시정지');self.resume_button=QtWidgets.QPushButton('계속');self.stop_button=QtWidgets.QPushButton('Queue 중단')
        for b in (self.run_button,self.pause_button,self.resume_button,self.stop_button):row.addWidget(b)
        self.run_button.clicked.connect(self.start);self.pause_button.clicked.connect(self.pause);self.resume_button.clicked.connect(self.resume);self.stop_button.clicked.connect(self.shutdown)
        self.status=QtWidgets.QLabel('대기 중');self.status.setWordWrap(True);layout.addWidget(self.status);self.controls()
    def refresh(self,select=None):
        self.table.setRowCount(len(self.jobs))
        for i,j in enumerate(self.jobs):
            for k,v in enumerate((j['name'],j['repeat'],j['on_failure'],j['filename'])):self.table.setItem(i,k,QtWidgets.QTableWidgetItem(str(v)))
        if select is not None:self.table.selectRow(select)
    def add_file(self):
        if self.still_running():return
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Add workflow',str(Path(__file__).resolve().parents[1]/'workflow'),'Python (*.py)')
        if path:
            try:self.jobs.append(freeze_job(path));self.dirty=True;self.refresh(len(self.jobs)-1);self.edit_job()
            except Exception as exc:self.status.setText(str(exc))
    def edit_job(self):
        i=self.table.currentRow()
        if self.still_running() or not 0<=i<len(self.jobs):return
        job=deepcopy(self.jobs[i]);dialog=QtWidgets.QDialog(self);dialog.setWindowTitle('Workflow 조건');form=QtWidgets.QFormLayout(dialog)
        name=QtWidgets.QLineEdit(job['name']);repeat=QtWidgets.QSpinBox();repeat.setRange(1,10000);repeat.setValue(job['repeat']);policy=QtWidgets.QComboBox();policy.addItems(['stop','skip']);policy.setCurrentText(job['on_failure'])
        params=QtWidgets.QPlainTextEdit(json.dumps(job['parameters'],ensure_ascii=False,indent=2));params.setMinimumSize(500,240)
        reload=QtWidgets.QCheckBox('Python 소스를 현재 파일에서 다시 가져오기');form.addRow('이름',name);form.addRow('반복',repeat);form.addRow('실패 시',policy);form.addRow('devices.parameters (JSON)',params);form.addRow(reload)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);form.addRow(buttons)
        if dialog.exec_()==QtWidgets.QDialog.Accepted:
            try:
                if reload.isChecked():
                    new=freeze_job(job['filename']);job.update(source=new['source'],sha256=new['sha256'])
                job.update(name=name.text().strip(),repeat=repeat.value(),on_failure=policy.currentText(),parameters=json.loads(params.toPlainText()))
                validate_plan(dict(schema_version=1,repeat=1,jobs=[job]));self.jobs[i]=job;self.dirty=True;self.refresh(i)
            except Exception as exc:self.status.setText('설정 오류: '+str(exc))
    def duplicate(self):
        i=self.table.currentRow()
        if not self.still_running() and 0<=i<len(self.jobs):
            j=deepcopy(self.jobs[i]);j['id']=uuid4().hex;self.jobs.insert(i+1,j);self.dirty=True;self.refresh(i+1)
    def remove(self):
        i=self.table.currentRow()
        if not self.still_running() and 0<=i<len(self.jobs):self.jobs.pop(i);self.dirty=True;self.refresh()
    def move(self,offset):
        i=self.table.currentRow();other=i+offset
        if not self.still_running() and 0<=i<len(self.jobs) and 0<=other<len(self.jobs):self.jobs[i],self.jobs[other]=self.jobs[other],self.jobs[i];self.dirty=True;self.refresh(other)
    def plan(self):return validate_plan(dict(schema_version=1,repeat=self.repeat.value(),jobs=self.jobs))
    def save_plan(self):
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Save Queue','queue.local.json','JSON (*.json)')
        if not path:return False
        try:save(path,self.plan());self.dirty=False;self.status.setText(path);return True
        except Exception as exc:self.status.setText(str(exc));return False
    def load_plan(self):
        if self.still_running() or not self.confirm_close():return
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Load Queue','','JSON (*.json)')
        if path:
            try:
                p=validate_plan(read(path));self.jobs=p['jobs'];self.repeat.setValue(p['repeat']);self.dirty=False;self.refresh();self.status.setText(path)
            except Exception as exc:self.status.setText(str(exc))
    def choose_folder(self):
        path=QtWidgets.QFileDialog.getExistingDirectory(self,'Queue save folder',self.directory.text())
        if path:self.directory.setText(path)
    def start(self):
        if self.still_running():return
        try:
            if not self.directory.text().strip():raise ValueError('Choose save folder')
            self.thread=QueueThread(self.bindings_provider(),self.plan(),self.directory.text(),self);self.thread.changed.connect(self.progress);self.thread.failed.connect(self.status.setText);self.thread.finished.connect(self.controls);self.thread.start();self.status.setText('Starting Queue');self.controls()
        except Exception as exc:self.status.setText(str(exc))
    def progress(self,state):
        current=next((p['name'] for p in state['steps'] if p['status']=='running'),'')
        done=sum(p['status'] in ('completed','failed','cancelled') for p in state['steps'])
        self.status.setText(f"{state['status']} · {done}/{len(state['steps'])} · {current} · {state['folder']}");self.state_changed.emit(state)
    def pause(self):
        if self.still_running():self.thread.runner.pause_after_current();self.status.setText('현재 workflow 종료 후 일시정지합니다.')
    def resume(self):
        if self.still_running():self.thread.runner.resume()
    def shutdown(self):
        if self.still_running():self.thread.runner.cancel();self.status.setText('중단 중 — 현재 workflow 정리·저장을 기다립니다.')
    def still_running(self):return self.thread is not None and self.thread.isRunning()
    def controls(self):
        active=self.still_running()
        for b in (*self.edit_buttons,self.repeat,self.directory,self.folder_button,self.run_button):b.setEnabled(not active)
        for b in (self.pause_button,self.resume_button,self.stop_button):b.setEnabled(active)
    def confirm_close(self):
        if not self.dirty:return True
        answer=QtWidgets.QMessageBox.question(self,'Queue','수정한 Queue 구성을 저장할까요?',QtWidgets.QMessageBox.Save|QtWidgets.QMessageBox.Discard|QtWidgets.QMessageBox.Cancel)
        return self.save_plan() if answer==QtWidgets.QMessageBox.Save else answer==QtWidgets.QMessageBox.Discard
