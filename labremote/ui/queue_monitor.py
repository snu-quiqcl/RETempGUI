"""Read-only queue outcomes and metrics, independent of hardware polling."""
import json
import math
from pathlib import Path
from PyQt5 import QtCore,QtGui,QtWidgets
from labremote.runtime.workflow_queue import read

class ManifestReader(QtCore.QThread):
    loaded=QtCore.pyqtSignal(object)
    failed=QtCore.pyqtSignal(str)
    def __init__(self,path,parent=None):super().__init__(parent);self.path=path
    def run(self):
        try:
            data=read(self.path)
            if not isinstance(data,dict) or data.get('schema_version')!=1 or not isinstance(data.get('steps'),list) or not isinstance(data.get('status'),str):raise ValueError('Not a workflow Queue manifest')
            for step in data['steps']:
                if not isinstance(step,dict) or not all(k in step for k in ('step_id','name','iteration','job_repeat','status')):raise ValueError('Invalid Queue step')
                if 'elapsed_s' in step and not isinstance(step['elapsed_s'],(int,float)):raise ValueError('Invalid step duration')
                result=step.get('result',{})
                if not isinstance(result,dict) or not isinstance(result.get('metrics',{}),dict):raise ValueError('Invalid step result')
            data['folder']=str(Path(self.path).resolve().parent);self.loaded.emit(data)
        except Exception as exc:self.failed.emit(str(exc))

class QueueMonitor(QtWidgets.QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.latest=None;self.current=None;self.follow=True;self.reader=None
        layout=QtWidgets.QVBoxLayout(self);row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        for title,fn in [('현재 Queue 보기',self.show_current),('저장된 Queue 열기',self.open_manifest),('결과 폴더 열기',self.open_folder)]:
            button=QtWidgets.QPushButton(title);button.clicked.connect(fn);row.addWidget(button)
        row.addStretch();self.metric=QtWidgets.QComboBox();self.metric.addItem('실행 시간 (s)','elapsed_s');row.addWidget(self.metric);self.metric.currentIndexChanged.connect(self.draw)
        self.status=QtWidgets.QLabel('Queue 실행 결과를 기다립니다.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.table=QtWidgets.QTableWidget(0,7);self.table.setHorizontalHeaderLabels(['Step','Workflow','전체 반복','작업 반복','상태','시간(s)','실패 원인'])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers);self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows);self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents);self.table.horizontalHeader().setStretchLastSection(True);layout.addWidget(self.table,2)
        self.table.itemSelectionChanged.connect(self.selection)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        self.figure=Figure(figsize=(8,2));self.axis=self.figure.subplots();self.canvas=FigureCanvasQTAgg(self.figure);layout.addWidget(self.canvas,1)
        self.details=QtWidgets.QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(170);layout.addWidget(self.details)
    def accept_live(self,state):
        self.latest=state
        if self.follow:self.show_manifest(state)
    def show_current(self):
        self.follow=True
        if self.latest:self.show_manifest(self.latest)
    def show_manifest(self,state):
        self.current=state;steps=state['steps'];counts={s:sum(p['status']==s for p in steps) for s in ('completed','failed','cancelled','running','pending')}
        self.status.setText(f"{state['status']} · 성공 {counts['completed']} / 실패 {counts['failed']} / 취소 {counts['cancelled']} / 실행 {counts['running']} / 대기 {counts['pending']} · {state.get('folder','')}"+(' · '+state['error'] if state.get('error') else ''))
        selected=self.table.currentRow();self.table.setRowCount(len(steps))
        for i,p in enumerate(steps):
            values=[p['step_id'],p['name'],p['iteration'],p['job_repeat'],p['status'],f"{p['elapsed_s']:.3f}" if 'elapsed_s' in p else '',p.get('result',{}).get('reason',p.get('reason',''))]
            for j,v in enumerate(values):self.table.setItem(i,j,QtWidgets.QTableWidgetItem(str(v)))
        keys=sorted({k for p in steps for k,v in p.get('result',{}).get('metrics',{}).items() if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)})
        choice=self.metric.currentData()
        with QtCore.QSignalBlocker(self.metric):
            self.metric.clear();self.metric.addItem('실행 시간 (s)','elapsed_s')
            for k in keys:self.metric.addItem(k,'metric:'+k)
            index=self.metric.findData(choice);self.metric.setCurrentIndex(max(0,index))
        if 0<=selected<len(steps):self.table.selectRow(selected)
        self.selection();self.draw()
    def draw(self):
        if not self.current:return
        key=self.metric.currentData();x=[];y=[]
        for i,p in enumerate(self.current['steps']):
            v=p.get('elapsed_s') if key=='elapsed_s' else p.get('result',{}).get('metrics',{}).get((key or '')[7:])
            if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v):x.append(i+1);y.append(v)
        self.axis.clear();self.axis.plot(x,y,'o-');self.axis.set(xlabel='Execution step',ylabel=self.metric.currentText());self.axis.grid(True,alpha=.3);self.figure.subplots_adjust(left=.12,right=.97,bottom=.25,top=.95);self.canvas.draw_idle()
    def selection(self):
        i=self.table.currentRow()
        if self.current and 0<=i<len(self.current['steps']):self.details.setPlainText(json.dumps(self.current['steps'][i],ensure_ascii=False,indent=2)[:50000])
    def open_manifest(self):
        if self.still_running():return
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Open Queue manifest','','Queue (queue_manifest.json)')
        if path:
            self.follow=False;self.reader=ManifestReader(path,self);self.reader.loaded.connect(self.show_manifest);self.reader.failed.connect(self.status.setText);self.reader.start()
    def open_folder(self):
        if not self.current:return
        i=self.table.currentRow();path=Path(self.current.get('folder',''))
        if 0<=i<len(self.current['steps']):path=path/self.current['steps'][i].get('directory','')
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))
    def still_running(self):return self.reader is not None and self.reader.isRunning()
