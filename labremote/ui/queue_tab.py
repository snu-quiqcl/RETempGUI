import json
from copy import deepcopy
from pathlib import Path
from labremote.data_paths import data_directory, resolve_data_directory
from uuid import uuid4
from PyQt5 import QtCore,QtWidgets
from labremote.runtime.workflow_queue import QueueRunner,freeze_job,validate_plan,read,save,is_group,make_group

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
    plan_changed=QtCore.pyqtSignal(object)
    def __init__(self,bindings_provider,parent=None):
        super().__init__(parent);self.bindings_provider=bindings_provider;self.jobs=[];self.thread=None;self.dirty=False
        layout=QtWidgets.QVBoxLayout(self);layout.addWidget(QtWidgets.QLabel('각 작업은 독립된 main(devices) workflow입니다. 추가한 Python 소스와 JSON 변수를 사본으로 보관합니다.'))
        row=QtWidgets.QHBoxLayout();layout.addLayout(row);self.edit_buttons=[]
        for label,fn in [('Workflow 추가',self.add_file),('편집',self.edit_job),('복제',self.duplicate),('삭제',self.remove),('위',lambda:self.move(-1)),('아래',lambda:self.move(1)),('Queue 불러오기',self.load_plan),('Queue 저장',self.save_plan)]:
            b=QtWidgets.QPushButton(label);b.clicked.connect(fn);row.addWidget(b);self.edit_buttons.append(b)
        self.table=QtWidgets.QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['Workflow','반복','실패 정책','파일','Monitor'])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows);self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection);self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers);self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents);self.table.horizontalHeader().setStretchLastSection(True);layout.addWidget(self.table,1)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        for label,fn in [('선택 항목 묶기',self.group_selected),('그룹 해제',self.ungroup),('각도별 그룹 생성',self.angle_groups),('선택 그룹 안에 추가',lambda:self.add_file(top_level=False))]:
            button=QtWidgets.QPushButton(label);button.clicked.connect(fn);row.addWidget(button);self.edit_buttons.append(button)
        row.addWidget(QtWidgets.QLabel('Workflow 추가는 그룹 밖에 추가합니다. 그룹 안에 넣으려면 그룹을 선택하고 ‘선택 그룹 안에 추가’를 누르세요.'))
        self._row_refs=[]
        self.table.cellDoubleClicked.connect(lambda *_:self.edit_job())
        row=QtWidgets.QHBoxLayout();layout.addLayout(row);row.addWidget(QtWidgets.QLabel('전체 목록 반복'));self.repeat=QtWidgets.QSpinBox();self.repeat.setRange(1,10000);row.addWidget(self.repeat);self.repeat.valueChanged.connect(lambda *_:setattr(self,'dirty',True))
        self.directory=QtWidgets.QLineEdit(str(data_directory('queues')));row.addWidget(self.directory,1);self.folder_button=QtWidgets.QPushButton('저장 폴더');row.addWidget(self.folder_button);self.folder_button.clicked.connect(self.choose_folder)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        self.run_button=QtWidgets.QPushButton('Queue 실행');self.pause_button=QtWidgets.QPushButton('현재 작업 후 일시정지');self.resume_button=QtWidgets.QPushButton('계속');self.stop_button=QtWidgets.QPushButton('Queue 중단')
        for b in (self.run_button,self.pause_button,self.resume_button,self.stop_button):row.addWidget(b)
        self.run_button.clicked.connect(self.start);self.pause_button.clicked.connect(self.pause);self.resume_button.clicked.connect(self.resume);self.stop_button.clicked.connect(self.shutdown)
        self.status=QtWidgets.QLabel('대기 중');self.status.setWordWrap(True);layout.addWidget(self.status);self.controls()
        self.repeat.valueChanged.connect(self.publish_plan)
    def publish_plan(self,*_):
        if not self.still_running():
            self.plan_changed.emit(deepcopy(dict(schema_version=2 if any(is_group(j) for j in self.jobs) else 1,repeat=self.repeat.value(),jobs=self.jobs)))
    def refresh(self,select=None):
        self._row_refs=[];entries=[]
        for i,j in enumerate(self.jobs):
            self._row_refs.append((i,None));entries.append((j,False))
            if is_group(j):
                for child,k in enumerate(j['jobs']):
                    self._row_refs.append((i,child));entries.append((k,True))
        self.table.setRowCount(len(entries))
        for row,(j,child) in enumerate(entries):
            label=('    ↳ ' if child else '▾ ' if is_group(j) else '')+j['name']
            if not is_group(j):
                from labremote.runtime.workflow_queue import target_fpga
                target=target_fpga(j)
                if target:label+=' · '+target
            values=(label,j['repeat'],j['on_failure'],f"{len(j['jobs'])} workflows" if is_group(j) else j['filename'])
            from labremote.runtime.monitor_config import settings
            m=settings(j) if not is_group(j) else None
            values+=('—' if m is None else {'none':'없음','ion':'Ion Check','spam':'SPAM','ent':'RE'}[m['kind']]+(' · '+m['title'] if m['title'] else ''),)
            for k,v in enumerate(values):
                cell=QtWidgets.QTableWidgetItem(str(v))
                if is_group(j):
                    font=cell.font();font.setBold(True);cell.setFont(font)
                if child and k==2:cell.setToolTip('그룹 안에서는 그룹의 실패 정책이 적용됩니다.')
                self.table.setItem(row,k,cell)
        if select is not None:
            ref=select if isinstance(select,tuple) else (select,None)
            if ref in self._row_refs:self.table.selectRow(self._row_refs.index(ref))
        self.publish_plan()

    def selected(self):
        row=self.table.currentRow()
        if not 0<=row<len(self._row_refs):return None
        top,child=self._row_refs[row]
        return (self.jobs,top,(top,None)) if child is None else (self.jobs[top]['jobs'],child,(top,child))

    def group_selected(self):
        if self.still_running():return
        refs=[self._row_refs[index.row()] for index in self.table.selectionModel().selectedRows()]
        indices=sorted(top for top,child in refs if child is None)
        if (not refs or len(indices)!=len(refs) or indices!=list(range(indices[0],indices[-1]+1))
                or any(is_group(self.jobs[i]) for i in indices)):
            self.status.setText('연속된 최상위 workflow만 선택해 주세요. 중첩 그룹은 지원하지 않습니다.');return
        group=make_group([self.jobs[i] for i in indices])
        self.jobs[indices[0]:indices[-1]+1]=[group];self.dirty=True;self.refresh(indices[0]);self.edit_job()

    def ungroup(self):
        selected=self.selected()
        if self.still_running() or selected is None:return
        items,i,ref=selected
        if not is_group(items[i]):return
        items[i:i+1]=items[i]['jobs'];self.dirty=True;self.refresh(ref[0])

    @staticmethod
    def copy_item(item):
        item=deepcopy(item);item['id']=uuid4().hex
        if is_group(item):
            for child in item['jobs']:child['id']=uuid4().hex
        return item

    @staticmethod
    def apply_angle(group,basis,phase):
        targets=[j for j in group['jobs'] if Path(j['filename']).name in ('queue_entanglement.py','re.py')
                 and isinstance(j['parameters'].get('settings'),dict)]
        if not targets:raise ValueError('그룹 안에 Entanglement 탭에서 추가한 얽힘 workflow가 필요합니다.')
        from labremote.entanglement.config import validate
        for job in targets:
            settings=deepcopy(job['parameters']['settings'])
            settings.update(basis=basis,phase_magnitude_deg=phase)
            validate(settings)
            job['parameters']['settings']=settings

    def angle_groups(self):
        selected=self.selected()
        if self.still_running() or selected is None:return
        items,i,ref=selected
        if not is_group(items[i]):self.status.setText('복제할 Repeat Group을 선택해 주세요.');return
        dialog=QtWidgets.QDialog(self);dialog.setWindowTitle('각도별 그룹 생성');form=QtWidgets.QFormLayout(dialog)
        angles=QtWidgets.QLineEdit('0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330')
        form.addRow('MW detuned 각도 목록 (deg)',angles)
        form.addRow(QtWidgets.QLabel('선택한 그룹 다음에 각도별 복사본을 추가합니다. 원본 그룹은 유지합니다.'))
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);form.addRow(buttons)
        if dialog.exec_()!=QtWidgets.QDialog.Accepted:return
        try:
            import math
            values=[float(v.strip()) for v in angles.text().split(',')]
            if not values or len(values)>1000 or any(not math.isfinite(v) or not 0<=v<=360 for v in values):raise ValueError('각도는 0..360 범위여야 합니다 (최대 1000개).')
            groups=[]
            for phase in values:
                group=self.copy_item(items[i]);group['name']=f'MW detuned {phase:g}°'
                self.apply_angle(group,'mw_detuned',phase);groups.append(group)
            candidate=self.jobs[:ref[0]+1]+groups+self.jobs[ref[0]+1:]
            validate_plan(dict(schema_version=2,repeat=self.repeat.value(),jobs=candidate))
            self.jobs=candidate;self.dirty=True;self.refresh(ref[0]+1)
        except Exception as exc:self.status.setText('설정 오류: '+str(exc))

    def edit_group(self,items,i,ref):
        group=deepcopy(items[i]);dialog=QtWidgets.QDialog(self);dialog.setWindowTitle('Repeat Group');form=QtWidgets.QFormLayout(dialog)
        name=QtWidgets.QLineEdit(group['name']);repeat=QtWidgets.QSpinBox();repeat.setRange(1,10000);repeat.setValue(group['repeat'])
        policy=QtWidgets.QComboBox();policy.addItem('Queue 중단','stop');policy.addItem('현재 반복 건너뛰기','skip_iteration');policy.setCurrentIndex(max(0,policy.findData(group['on_failure'])))
        form.addRow('그룹 이름',name);form.addRow('묶음 반복 N',repeat);form.addRow('실패 시 (자식 정책보다 우선)',policy)
        form.addRow(QtWidgets.QLabel('이온 loss·통신 오류 등 계속 진행 불가 결과는 항상 Queue를 중단합니다.'))
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);form.addRow(buttons)
        if dialog.exec_()!=QtWidgets.QDialog.Accepted:return
        try:
            group.update(name=name.text().strip(),repeat=repeat.value(),on_failure=policy.currentData())
            candidate=deepcopy(self.jobs);candidate[ref[0]]=group
            validate_plan(dict(schema_version=2,repeat=self.repeat.value(),jobs=candidate))
            items[i]=group;self.dirty=True;self.refresh(ref)
        except Exception as exc:self.status.setText('설정 오류: '+str(exc))
    def add_file(self,checked=False,*,top_level=True):
        if self.still_running():return
        selected=self.selected()
        top=selected[2][0] if selected else None
        if not top_level and (top is None or not is_group(self.jobs[top])):
            self.status.setText('Workflow를 추가할 Repeat Group을 선택해 주세요.');return
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Add workflow',str(Path(__file__).resolve().parents[1]/'workflow'),'Python (*.py)')
        if path:
            try:
                job=freeze_job(path)
                from labremote.runtime.workflow_queue import target_fpga
                target=target_fpga(job)
                if target:
                    worker=next((bridge.worker for family,bridge in self.bindings_provider().values() if family=='fpga' and bridge.worker.name==target),None)
                    if worker is None:raise ValueError('Workflow 대상 FPGA를 먼저 연결하세요: '+target)
                    job.update(fpga_id=target,fpga_profiles={target:worker.profile.document()})
                selected=self.selected()
                top=selected[2][0] if selected else None
                if not top_level and top is not None and is_group(self.jobs[top]):
                    self.jobs[top]['jobs'].append(job);ref=(top,len(self.jobs[top]['jobs'])-1)
                else:self.jobs.append(job);ref=(len(self.jobs)-1,None)
                self.dirty=True;self.refresh(ref);self.edit_job()
            except Exception as exc:self.status.setText(str(exc))
    def edit_job(self):
        selected=self.selected()
        if self.still_running() or selected is None:return
        items,i,ref=selected
        if is_group(items[i]):return self.edit_group(items,i,ref)
        from labremote.ui.workflow_parameters import WorkflowJobDialog
        dialog=WorkflowJobDialog(items[i],self,bindings_provider=self.bindings_provider)
        if dialog.exec_()==QtWidgets.QDialog.Accepted:
            items[i]=dialog.job;self.dirty=True;self.refresh(ref)
    def duplicate(self):
        selected=self.selected()
        if not self.still_running() and selected is not None:
            items,i,ref=selected;items.insert(i+1,self.copy_item(items[i]));self.dirty=True
            self.refresh((ref[0],i+1) if ref[1] is not None else i+1)
    def remove(self):
        selected=self.selected()
        if not self.still_running() and selected is not None:
            items,i,ref=selected;items.pop(i)
            if ref[1] is not None and not items:self.jobs.pop(ref[0])
            self.dirty=True;self.refresh()
    def move(self,offset):
        selected=self.selected()
        if self.still_running() or selected is None:return
        items,i,ref=selected;other=i+offset
        if 0<=other<len(items):
            items[i],items[other]=items[other],items[i];self.dirty=True
            self.refresh((ref[0],other) if ref[1] is not None else other)
    def plan(self):return validate_plan(dict(schema_version=2 if any(is_group(j) for j in self.jobs) else 1,repeat=self.repeat.value(),jobs=self.jobs))
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
            owner=getattr(self.bindings_provider,'__self__',None)
            guard=getattr(owner,'_assert_workflow_ready',None)
            if guard is not None:guard()
            if not self.directory.text().strip():raise ValueError('Choose save folder')
            self.thread=QueueThread(self.bindings_provider(),self.plan(),self.directory.text(),self);self.thread.changed.connect(self.progress);self.thread.failed.connect(self.status.setText);self.thread.finished.connect(self.controls);self.thread.start();self.status.setText('Starting Queue');self.controls()
        except Exception as exc:self.status.setText(str(exc))
    def progress(self,state):
        current=next(((f"{p['group_name']} [{p['group_iteration']}/{p['group_repeat']}] / " if 'group_id' in p else '')+p['name'] for p in state['steps'] if p['status']=='running'),'')
        done=sum(p['status'] in ('completed','failed','cancelled','skipped') for p in state['steps'])
        self.status.setText(f"{state['status']} · {done}/{len(state['steps'])} · {current} · {state.get('waiting_reason','')} · {state['folder']}");self.state_changed.emit(state)
    def pause(self):
        if self.still_running():self.thread.runner.pause_after_current();self.status.setText('현재 workflow 종료 후 일시정지합니다.')
    def resume(self):
        if self.still_running():self.thread.runner.resume(self.bindings_provider())
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
