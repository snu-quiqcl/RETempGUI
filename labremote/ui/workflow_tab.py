"""File-based main(devices) workflow editor and background execution."""
from pathlib import Path
from PyQt5 import QtCore, QtGui, QtWidgets
from labremote.api.devices import SUPPORTED_FAMILIES
from labremote.runtime.errors import OperationCancelled
from labremote.runtime.workflow_runner import run_workflow
from labremote.runtime.workflow_loader import validate_workflow, load_workflow


class WorkflowThread(QtCore.QThread):
    result_ready = QtCore.pyqtSignal(object)
    error_ready = QtCore.pyqtSignal(str, bool)

    def __init__(self, source, filename, bindings, parent=None):
        super().__init__(parent)
        self.source, self.filename = source, filename
        self.bindings = dict(bindings)
        from labremote.devices.fpga.mapping import profiles_from_bindings
        self.fpga_profiles = profiles_from_bindings(self.bindings)
        self.fpga_id=next(iter(self.fpga_profiles)) if len(self.fpga_profiles)==1 else None
        from labremote.runtime.jobs import CancellationToken
        self.stop_event = CancellationToken()

    def run(self):
        try:
            if self.stop_event.is_set(): raise OperationCancelled('Stopped before loading workflow')
            from labremote.runtime.workflow_result import workflow_session
            with workflow_session(), load_workflow(self.source, self.filename) as workflow:
                result = run_workflow(self.bindings, workflow, stop_event=self.stop_event, fpga_profiles=self.fpga_profiles,fpga_id=self.fpga_id)
            self.result_ready.emit(result)
        except Exception as error:
            self.error_ready.emit(f'{type(error).__name__}: {error}', isinstance(error, OperationCancelled))

    def cancel(self): self.stop_event.set()


class WorkflowTab(QtWidgets.QWidget):
    idle = QtCore.pyqtSignal()

    def __init__(self, bindings_provider, parent=None):
        super().__init__(parent)
        self.bindings_provider = bindings_provider
        self.thread = None
        self.last_result = None
        self.filename = None
        self.workflow_root = Path(__file__).resolve().parents[1] / 'workflow'
        layout = QtWidgets.QVBoxLayout(self)
        self.fpga_selector=QtWidgets.QComboBox();self.fpga_selector.setProperty('persistInput',False)
        self.fpga_selector.addItem('FPGA 미사용',None);layout.addWidget(self.fpga_selector)
        self.fixed_fpga=None
        self.target_timer=QtCore.QTimer(self);self.target_timer.setInterval(300)
        self.target_timer.timeout.connect(self.refresh_fpga);self.target_timer.start()
        note = QtWidgets.QLabel('파일의 main(devices)를 실행합니다. 각 operation 뒤에 .wait()를 붙이면 순서대로 실행됩니다.')
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QtWidgets.QHBoxLayout()
        self.file_picker = QtWidgets.QComboBox()
        self.load_button = QtWidgets.QPushButton('파일 열기')
        self.reload_button = QtWidgets.QPushButton('다시 불러오기')
        row.addWidget(self.file_picker, 1)
        row.addWidget(self.load_button)
        row.addWidget(self.reload_button)
        layout.addLayout(row)
        self.path_label = QtWidgets.QLabel()
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)
        self.source = QtWidgets.QPlainTextEdit()
        self.source.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        self.source.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.source.setTabStopDistance(self.source.fontMetrics().horizontalAdvance(' ') * 4)
        self.source.setMinimumHeight(360)
        row = QtWidgets.QHBoxLayout()
        self.save_button = QtWidgets.QPushButton('저장')
        self.save_as_button = QtWidgets.QPushButton('다른 이름으로 저장')
        self.run_button = QtWidgets.QPushButton('저장 후 실행')
        self.stop_button = QtWidgets.QPushButton('중단')
        for button in (self.save_button, self.save_as_button, self.run_button, self.stop_button): row.addWidget(button)
        self.queue_button=QtWidgets.QPushButton('Queue에 추가');row.addWidget(self.queue_button)
        self.queue_button.clicked.connect(self.add_to_queue)
        row.addStretch(1)
        layout.addLayout(row)
        self.status = QtWidgets.QLabel('대기 중')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(self.source, 1)
        self.file_picker.currentIndexChanged.connect(self._choose_file)
        self.load_button.clicked.connect(self.open_file)
        self.reload_button.clicked.connect(self.refresh_files)
        self.save_button.clicked.connect(self.save_code)
        self.save_as_button.clicked.connect(self.save_as)
        self.run_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.cancel)
        self.source.document().modificationChanged.connect(self._modified)
        self.save_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence.Save, self)
        self.save_shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
        self.save_shortcut.activated.connect(self.save_code)
        self.refresh_files()
        self._editing(True)

    def refresh_fpga(self):
        if self.still_running():return
        selected=self.fixed_fpga or self.fpga_selector.currentData()
        items=[('FPGA 미사용',None)]
        for family,bridge in self.bindings_provider().values():
            if family=='fpga':items.append((bridge.worker.profile.alias+' · '+bridge.worker.name,bridge.worker.name))
        if selected and selected not in [n for _,n in items]:items.append((selected+' · 연결 끊김',selected))
        previous=[(self.fpga_selector.itemText(i),self.fpga_selector.itemData(i)) for i in range(self.fpga_selector.count())]
        if previous!=items:
            with QtCore.QSignalBlocker(self.fpga_selector):
                self.fpga_selector.clear()
                for title,name in items:self.fpga_selector.addItem(title,name)
                self.fpga_selector.setCurrentIndex(max(0,self.fpga_selector.findData(selected)))

    def add_to_queue(self):
        try:
            if self.still_running():raise RuntimeError('실행 완료 후 Queue에 추가하세요.')
            host=self.parent()
            while host is not None and not hasattr(host,'queue_tab'):host=host.parent()
            if host is None:
                owner=getattr(self.bindings_provider,'__self__',None)
                host=getattr(owner,'host',owner)
            queue=getattr(host,'queue_tab',None)
            if queue is None or queue.still_running():raise RuntimeError('편집 가능한 Queue가 없습니다.')
            from labremote.runtime.experiment_jobs import source_job
            selected=self.fixed_fpga or self.fpga_selector.currentData()
            worker=next((bridge.worker for family,bridge in self.bindings_provider().values() if family=='fpga' and bridge.worker.name==selected),None)
            if selected and worker is None:raise ValueError('선택한 FPGA를 연결하세요.')
            job=source_job(self.source.toPlainText(),self.filename or 'workflow.py','Workflow',{},worker.profile if worker else None)
            from labremote.runtime.workflow_queue import validate_plan, target_fpga
            import ast
            uses_fpga=any(isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='fpga' for node in ast.walk(ast.parse(job['source'])))
            if (uses_fpga or target_fpga(job)) and worker is None:
                raise ValueError('Queue에 저장할 FPGA를 먼저 선택하세요.')
            validate_plan(dict(schema_version=1,repeat=1,jobs=[job]))
            queue.jobs.append(job);queue.dirty=True;queue.refresh(len(queue.jobs)-1)
            self.status.setText('현재 코드 · FPGA · 핀 매핑을 Queue에 저장했습니다.')
        except Exception as exc:self.status.setText(str(exc))

    def _modified(self, modified):
        self.path_label.setText((self.filename or '파일을 선택하세요') + ('  • 수정됨' if modified else ''))

    def _select_current(self):
        with QtCore.QSignalBlocker(self.file_picker):
            self.file_picker.setCurrentIndex(self.file_picker.findData(self.filename))

    def confirm_close(self):
        if not self.source.document().isModified(): return True
        choice = QtWidgets.QMessageBox.question(self, '변경 내용 저장', '수정한 코드를 저장할까요?',
            QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Save)
        if choice == QtWidgets.QMessageBox.Save: return self.save_code()
        return choice == QtWidgets.QMessageBox.Discard

    def refresh_files(self):
        if self.still_running() or not self.confirm_close(): return
        previous = self.filename
        with QtCore.QSignalBlocker(self.file_picker):
            self.file_picker.clear()
            files = sorted(p for p in self.workflow_root.glob('*.py') if not p.name.startswith('_'))
            for path in files: self.file_picker.addItem(path.name, str(path.resolve()))
        target = previous or (str(self.workflow_root / 'read_windfreak.py') if (self.workflow_root / 'read_windfreak.py').exists()
                              else self.file_picker.itemData(0))
        if target: self.load_path(target, check_unsaved=False)

    def _choose_file(self, index):
        path = self.file_picker.itemData(index)
        if path and not self.load_path(path): self._select_current()

    def open_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Workflow Python 파일', str(self.workflow_root), 'Python (*.py)')
        if path: self.load_path(path)

    def load_path(self, path, *, check_unsaved=True):
        if self.still_running() or (check_unsaved and not self.confirm_close()): return False
        try:
            path = Path(path).resolve()
            source = path.read_text(encoding='utf-8-sig')
        except (OSError, UnicodeError) as error:
            self.status.setText(f'파일 오류: {error}')
            return False
        self.filename = str(path)
        with QtCore.QSignalBlocker(self.file_picker):
            if self.file_picker.findData(self.filename) < 0: self.file_picker.addItem(path.name, self.filename)
        self._select_current()
        self.source.setPlainText(source)
        self.source.document().setModified(False)
        self._modified(False)
        self.status.setText('대기 중 — main(devices)를 편집한 뒤 실행하세요.')
        self._editing(True)
        return True

    def _write(self, filename):
        # QSaveFile replaces the destination only after the complete write succeeds.
        output = QtCore.QSaveFile(filename)
        if not output.open(QtCore.QIODevice.WriteOnly):
            raise OSError(output.errorString())
        payload = self.source.toPlainText().encode('utf-8')
        if output.write(payload) != len(payload):
            output.cancelWriting()
            raise OSError(output.errorString())
        if not output.commit(): raise OSError(output.errorString())

    def save_code(self):
        if self.still_running(): return False
        if self.filename is None: return self.save_as()
        try: self._write(self.filename)
        except OSError as error:
            self.status.setText(f'저장 실패: {error}')
            return False
        self.source.document().setModified(False)
        self._modified(False)
        self.status.setText('저장 완료')
        return True

    def save_as(self):
        if self.still_running(): return False
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Workflow 저장', self.filename or str(self.workflow_root / 'workflow.py'), 'Python (*.py)')
        if not path: return False
        if not path.lower().endswith('.py'): path += '.py'
        try: self._write(path)
        except OSError as error:
            self.status.setText(f'저장 실패: {error}')
            return False
        self.source.document().setModified(False)
        return self.load_path(path, check_unsaved=False)

    def start(self):
        if self.still_running() or self.filename is None: return
        source = self.source.toPlainText()
        try: validate_workflow(source, self.filename)
        except (SyntaxError, ValueError) as error:
            self.status.setText(f'실행 불가: {error}')
            return
        try:
            owner=getattr(self.bindings_provider,'__self__',None)
            guard=getattr(owner,'_assert_workflow_ready',None)
            if guard is not None:guard()
            selected=self.fixed_fpga or self.fpga_selector.currentData()
            bindings = {key: value for key, value in self.bindings_provider().items() if value[0] in SUPPORTED_FAMILIES and (value[0]!='fpga' or value[1].worker.name==selected)}
            if selected and not any(v[0]=='fpga' for v in bindings.values()):raise RuntimeError('선택한 FPGA를 연결하세요.')
        except RuntimeError as error:
            self.status.setText(f'실행 불가: {error}');return
        if not bindings:
            self.status.setText('실행 불가: 먼저 사용할 장비를 연결하세요.')
            return
        if not self.save_code(): return
        # Neither later disk edits nor another file selection can change this run.
        self.thread = WorkflowThread(source, self.filename, bindings, self)
        self.thread.result_ready.connect(self._result)
        self.thread.error_ready.connect(self._error)
        self.thread.finished.connect(self._finished)
        self.last_result = None
        self.status.setText('실행 중')
        self._editing(False)
        self.thread.start()

    def _editing(self, enabled):
        for widget in (self.file_picker, self.load_button, self.reload_button, self.save_button, self.save_as_button):
            widget.setEnabled(enabled)
        self.source.setReadOnly(not enabled)
        self.run_button.setEnabled(enabled and self.filename is not None)
        self.stop_button.setEnabled(not enabled)

    def _result(self, result):
        self.last_result = result
        status=getattr(result,'status','completed')
        self.status.setText({'completed':'성공','failed':'실패','cancelled':'취소'}[status]+(' · '+result.reason if getattr(result,'reason','') else ''))

    def _error(self, message, stopped):
        from labremote.runtime.workflow_result import WorkflowResult
        self.last_result=WorkflowResult(status='cancelled' if stopped else 'failed',reason=message)
        self.status.setText(('취소: ' if stopped else '실패: ') + message)

    def _finished(self):
        self._editing(True)
        self.idle.emit()

    def cancel(self):
        if self.still_running():
            self.thread.cancel()
            self.stop_button.setEnabled(False)
            self.status.setText('중단 중 — 진행 중인 assign의 readback을 기다립니다.')

    def shutdown(self):
        self.target_timer.stop();self.cancel()

    def still_running(self):
        return self.thread is not None and self.thread.isRunning()
