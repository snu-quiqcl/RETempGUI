from pathlib import Path
from PyQt5 import QtCore,QtWidgets
from labremote.api.devices import device_api
from labremote.data_paths import tab_data_directory
from labremote.ion_check import config


class IonCheckTab(QtWidgets.QWidget):
    def __init__(self,worker,parent=None):
        super().__init__(parent);self.worker=worker;self.host=parent;self.api=device_api(worker)
        self.run_id=None;self.samples=[];self.run_settings=None;self.fields={};self.latest_result=None
        root=QtWidgets.QVBoxLayout(self)
        note=QtWidgets.QLabel('B → A + 7GA → C + 7GC · PMTA + PMTC 합산 · DAC swap 미연결')
        root.addWidget(note)
        split=QtWidgets.QSplitter();root.addWidget(split,1)
        left_scroll=QtWidgets.QScrollArea();left_scroll.setWidgetResizable(True);left_scroll.setMinimumWidth(290);split.addWidget(left_scroll)
        self.settings_panel=QtWidgets.QWidget();left_scroll.setWidget(self.settings_panel);left=QtWidgets.QVBoxLayout(self.settings_panel)
        group=QtWidgets.QGroupBox('측정 설정');form=QtWidgets.QFormLayout(group);left.addWidget(group)
        self.fpga=QtWidgets.QLabel(worker.name);form.addRow('FPGA',self.fpga)
        buttons=QtWidgets.QHBoxLayout()
        for label,callback in [('불러오기',self.load),('저장',self.save)]:
            button=QtWidgets.QPushButton(label);button.clicked.connect(callback);buttons.addWidget(button)
        form.addRow(buttons)
        for key,label,lo,hi,value in [('exposure_us','노출 시간 (µs)',1,10000,1000),('settle_us','안정화 대기 (µs)',1,10000,100),
                                    ('threshold_a','369A threshold',0,65535,0),('threshold_b','369B threshold',0,65535,0),('threshold_c','369C threshold',0,65535,0)]:
            box=QtWidgets.QSpinBox();box.setRange(lo,hi);box.setValue(value)
            if key.startswith('threshold'):box.setSpecialValueText('미설정')
            box.setKeyboardTracking(False);self.fields[key]=box;form.addRow(label,box)
        text=QtWidgets.QLabel('밝음: count ≥ threshold\n1회 측정은 threshold 없이도 가능합니다.');text.setWordWrap(True);form.addRow(text)
        group=QtWidgets.QGroupBox('Workflow 실행 조건');form=QtWidgets.QFormLayout(group);left.addWidget(group)
        n=QtWidgets.QSpinBox();n.setRange(1,10000);n.setValue(3);self.fields['max_attempts']=n;form.addRow('최대 측정 횟수 N',n)
        for key,label,lo,hi,value in [('retry_delay_s','재측정 간격 (s)',0,3600,.1),('timeout_s','측정 timeout (s)',.1,600,5)]:
            box=QtWidgets.QDoubleSpinBox();box.setRange(lo,hi);box.setDecimals(2);box.setValue(value);box.setSingleStep(.1);box.setKeyboardTracking(False)
            self.fields[key]=box;form.addRow(label,box)
        text=QtWidgets.QLabel('N은 최초 측정을 포함합니다.\n정상 확인 시 즉시 종료합니다.\nDAC 복구 없이 재측정만 수행합니다.');text.setWordWrap(True);form.addRow(text)
        self.directory=QtWidgets.QLineEdit(str(tab_data_directory(None,'ion_check')));left.addWidget(QtWidgets.QLabel('결과 저장 폴더'));left.addWidget(self.directory)
        choose=QtWidgets.QPushButton('폴더 선택');choose.clicked.connect(self.choose_folder);left.addWidget(choose);left.addStretch()
        right=QtWidgets.QWidget();split.addWidget(right);layout=QtWidgets.QVBoxLayout(right)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        self.once_button=QtWidgets.QPushButton('1회 측정');self.test_button=QtWidgets.QPushButton('최대 N회 workflow 테스트');self.stop_button=QtWidgets.QPushButton('중단');self.queue_button=QtWidgets.QPushButton('Queue에 추가')
        for button in (self.once_button,self.test_button,self.stop_button,self.queue_button):row.addWidget(button)
        self.once_button.clicked.connect(lambda:self.start('once'));self.test_button.clicked.connect(lambda:self.start('workflow'))
        self.stop_button.clicked.connect(self.stop);self.queue_button.clicked.connect(self.add_to_queue)
        self.measurement=QtWidgets.QLabel('통신·측정: 대기 중');self.decision=QtWidgets.QLabel('이온 판정: —');self.dac=QtWidgets.QLabel('DAC: 미연결 · 실행하지 않음')
        for label in (self.measurement,self.decision,self.dac):label.setWordWrap(True);layout.addWidget(label)
        self.count_labels={};self.state_labels={};row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        for key,title in [('a','369A · EA 확인'),('b','369B · 170 확인'),('c','369C · EC 확인')]:
            group=QtWidgets.QGroupBox(title);box=QtWidgets.QVBoxLayout(group)
            count=QtWidgets.QLabel('— count');font=count.font();font.setPointSize(20);count.setFont(font)
            state=QtWidgets.QLabel('threshold 미설정');box.addWidget(count);box.addWidget(state);row.addWidget(group)
            self.count_labels[key]=count;self.state_labels[key]=state
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        self.figure=Figure(figsize=(7,2.7));self.axis=self.figure.subplots();self.canvas=FigureCanvasQTAgg(self.figure);layout.addWidget(self.canvas,1)
        self.history=QtWidgets.QTableWidget(0,7);self.history.setHorizontalHeaderLabels(['회차','시각','A','B','C','이온 판정','DAC'])
        self.history.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers);self.history.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents);self.history.horizontalHeader().setStretchLastSection(True)
        self.history.setMaximumHeight(230);layout.addWidget(self.history)
        self.status=QtWidgets.QLabel('측정 종료 시 A/C·7GA/7GC ON, B OFF');self.status.setWordWrap(True);layout.addWidget(self.status)
        split.setSizes([310,850])
        try:self.populate(config.load())
        except Exception as exc:self.populate(config.defaults());self.status.setText('설정 파일 확인: '+str(exc))
        worker.task_progress.connect(self.progress)
        self.timer=QtCore.QTimer(self);self.timer.timeout.connect(self.controls);self.timer.start(200)
        self.draw();self.controls()

    def populate(self,c):
        c=config.validate(c)
        for key,box in self.fields.items():box.setValue(c[key] if c[key] is not None else 0)

    def value(self,require_thresholds=False):
        c=dict(schema_version=1,**{k:box.value() for k,box in self.fields.items()})
        for key in ('threshold_a','threshold_b','threshold_c'):
            if c[key]==0:c[key]=None
        return config.validate(c,require_thresholds)

    def load(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Ion Check 설정 불러오기',str(config.ROOT),'JSON (*.json)')
        if path:
            try:self.populate(config.load(path));self.status.setText('설정 불러옴: '+path)
            except Exception as exc:self.status.setText(str(exc))

    def save(self):
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Ion Check 설정 저장',str(config.ROOT/'ion_check.local.json'),'JSON (*.json)')
        if path:
            try:config.save(path,self.value());self.status.setText('설정 저장: '+path)
            except Exception as exc:self.status.setText(str(exc))

    def choose_folder(self):
        path=QtWidgets.QFileDialog.getExistingDirectory(self,'Ion Check 저장 폴더',self.directory.text())
        if path:self.directory.setText(path)

    def external_busy(self):
        return any(getattr(self.host,name,None) is not None and getattr(self.host,name).still_running() for name in ('workflow_tab','queue_tab'))

    def start(self,mode):
        try:
            if self.external_busy():raise RuntimeError('Workflow / Queue 실행을 먼저 종료하세요.')
            guard=getattr(self.host,'_assert_workflow_ready',None)
            if guard is not None:guard()
            if not self.directory.text().strip():raise ValueError('저장 폴더를 선택하세요.')
            c=self.value(require_thresholds=mode=='workflow')
            handle=self.api.run_ion_check(settings=c,mode=mode,directory=self.directory.text())
            if handle.done.is_set() and handle.error:raise handle.error
            self.status.setText('측정 시작 · DAC 미연결')
        except Exception as exc:self.status.setText(str(exc))
        self.controls()

    def stop(self):
        self.worker.ion_check_runner.cancel();self.status.setText('중단 중 · 출력 정리 완료를 기다립니다.')

    def add_to_queue(self):
        try:
            queue=getattr(self.host,'queue_tab',None)
            if queue is None:raise RuntimeError('메인 창의 Queue가 필요합니다.')
            if queue.still_running() or self.still_running():raise RuntimeError('현재 작업을 먼저 종료하세요.')
            from labremote.runtime.workflow_queue import freeze_job
            job=freeze_job(Path(__file__).resolve().parents[1]/'workflow/queue_ion_check.py',name='Ion Check · '+self.worker.name,
                           parameters=dict(fpga=self.worker.name,settings=self.value(True)))
            queue.jobs.append(job);queue.dirty=True;queue.refresh(len(queue.jobs)-1)
            self.status.setText('현재 설정 사본을 Queue에 추가했습니다. 최대 N회 판정으로 실행됩니다.')
        except Exception as exc:self.status.setText(str(exc))

    def progress(self,label,state):
        if label!='ION_CHECK':return
        if state.get('run_id')!=self.worker.ion_check_runner.state.get('run_id'):return
        if self.run_id!=state['run_id']:
            self.run_id=state['run_id'];self.samples=[];self.history.setRowCount(0);self.latest_result=None
            self.run_settings=state.get('settings');self.measurement.setText('통신·측정: 실행 중');self.decision.setText('이온 판정: —')
            for key in 'abc':self.count_labels[key].setText('— count');self.state_labels[key].setText('측정 대기')
            self.draw()
        if state.get('settings'):self.run_settings=state['settings']
        sample=state.get('sample')
        if sample and (not self.samples or sample['attempt']>self.samples[-1]['attempt']):
            self.samples.append(sample);self.measurement.setText('통신·측정: 측정값 수신 완료')
            self.decision.setText('이온 판정: '+config.LABELS[sample['decision']])
            for key in 'abc':
                self.count_labels[key].setText(str(sample['counts'][key])+' count')
                bright=sample['bright'][key];threshold=self.run_settings['threshold_'+key]
                self.state_labels[key].setText(('미판정' if bright is None else '밝음' if bright else '어두움')+f' · threshold {threshold if threshold is not None else "미설정"}')
            row=self.history.rowCount();self.history.insertRow(row)
            values=[sample['attempt'],sample['measured_at'].split('T')[-1],*[sample['counts'][k] for k in 'abc'],config.LABELS[sample['decision']],'미실행']
            for col,value in enumerate(values):self.history.setItem(row,col,QtWidgets.QTableWidgetItem(str(value)))
            self.history.scrollToBottom();self.draw()
        result=state.get('result')
        if result:
            self.latest_result=result
            self.measurement.setText('통신·측정: '+('정상 완료' if result['measurement_status']=='completed' else '중단' if result['status']=='cancelled' else '오류'))
            self.status.setText(f"{result['status']} · {result['reason']} · 출력 정리: {result['cleanup_status']}\n{result['folder']}")
        elif state.get('error'):
            self.measurement.setText('통신·측정: 오류');self.status.setText(state['error'])

    def draw(self):
        self.axis.clear()
        for key,color in [('a','#2874bd'),('b','#c58020'),('c','#8762ba')]:
            self.axis.plot([s['attempt'] for s in self.samples],[s['counts'][key] for s in self.samples],'.-',color=color,label='369'+key.upper())
            threshold=(self.run_settings or {}).get('threshold_'+key)
            if threshold is not None:self.axis.axhline(threshold,color=color,linestyle='--',alpha=.6)
        self.axis.set(xlabel='Measurement',ylabel='PMTA + PMTC counts');self.axis.grid(alpha=.2);self.axis.legend(loc='upper right');self.figure.tight_layout();self.canvas.draw_idle()

    def controls(self):
        worker=self.worker;running=self.still_running()
        busy=worker.has_requests() or worker.waveform_runner.running() or any(t.running() for t in worker._background_tasks)
        ready=worker.ps is not None and not worker.connection_error and not getattr(worker,'_closing',False) and not busy and not self.external_busy()
        self.once_button.setEnabled(ready);self.test_button.setEnabled(ready);self.stop_button.setEnabled(running)
        self.queue_button.setEnabled(not running and not self.external_busy());self.settings_panel.setEnabled(not running)

    def still_running(self):return self.worker.ion_check_runner.running()
    def shutdown(self):self.timer.stop();self.worker.ion_check_runner.cancel()
