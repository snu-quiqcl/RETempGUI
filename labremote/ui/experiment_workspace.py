from labremote.ui.responsive import bounded_combo
from labremote.ui.responsive import ScrollTabs
"""Shared experiment pages select a connected FPGA without moving running jobs."""
from pathlib import Path
from PyQt5 import QtCore, QtWidgets as W
from labremote.devices.fpga.mapping import scope
from .experiment_mapping import MappingEditor


def connected(worker):
    return worker.ps is not None and not worker.connection_error and not worker._closing and not worker._disconnecting


def busy(worker):
    return (getattr(worker,'_fpga_owner',None) is not None or worker.has_requests()
            or worker.waveform_runner.running() or any(t.running() for t in worker._background_tasks))



class ExperimentSlot(W.QWidget):
    def __init__(self,host,title,factory,parent=None):
        super().__init__(parent);self.host=host;self.title=title;self.factory=factory
        self.views={};self.selected=None;self.current=None;self._refreshing=False;self._pin_signatures={};self._selection_error=None
        self.root=W.QVBoxLayout(self)
        self.selection=W.QGroupBox('FPGA 선택');form=W.QVBoxLayout(self.selection)
        self.choice=W.QComboBox();bounded_combo(self.choice);self.choice.setProperty('persistInput',False);form.addWidget(self.choice)
        self.info=W.QLabel();self.info.setWordWrap(True);form.addWidget(self.info)
        self.queue_button=W.QPushButton('현재 조건으로 Queue에 추가');form.addWidget(self.queue_button)
        self.queue_button.clicked.connect(self.add_to_queue)
        self.root.addWidget(self.selection)
        self.empty=W.QLabel('FPGA 장비 창에서 연결한 뒤 사용할 장비를 선택하세요.');self.root.addWidget(self.empty)
        self.choice.currentIndexChanged.connect(self.choose)
        self.refresh()

    def worker(self):
        panel=self.host.family_tabs['fpga'].get(self.selected)
        return panel.worker if panel else None

    def bindings(self,name=None):
        name=self.selected if name is None else name
        return {key:value for key,value in self.host._bindings().items()
                if value[0]!='fpga' or value[1].worker.name==name}

    def refresh(self):
        workers={n:p.worker for n,p in self.host.family_tabs['fpga'].items()}
        items=[('FPGA 선택…',None)]
        items += [(w.profile.alias+' · '+n,n) for n,w in workers.items() if connected(w)]
        if self.selected and not any(n==self.selected for _,n in items):
            items.append((self.selected+' · 연결 끊김',self.selected))
        existing=[(self.choice.itemText(i),self.choice.itemData(i)) for i in range(self.choice.count())]
        if existing!=items:
            with QtCore.QSignalBlocker(self.choice):
                self.choice.clear()
                for title,name in items:self.choice.addItem(title,name)
                self.choice.setCurrentIndex(max(0,self.choice.findData(self.selected)))
        w=self.worker();active=w is not None and busy(w)
        self.choice.setEnabled(not active)
        ready=w is not None and connected(w)
        if ready and not active and not self._selection_error and (self.current is None or self._pin_signatures.get(self.selected)!=w.profile.document()['pins']):
            self.choose(force=True)
            return
        self.queue_button.setEnabled(ready and self.current is not None and not self.host.queue_tab.still_running())
        self.empty.setText('실험 화면을 열지 못했습니다. 위 오류를 확인하세요.' if self._selection_error else 'FPGA 장비 창에서 연결한 뒤 사용할 장비를 선택하세요.')
        if self._selection_error:self.info.setText(self._selection_error)
        elif w is None:self.info.setText('연결된 장비만 선택할 수 있습니다.')
        else:self.info.setText(('연결됨' if ready else '연결 끊김 · 재연결 후 실행하세요.')+
                              (' · 장비 사용 중' if active else '')+'\n각 FPGA의 저장된 실험 조건을 사용합니다.')
        if self.current is not None:
            for mapping in self.current.findChildren(MappingEditor):
                mapping.setEnabled(not active)
            # Keep the selector usable after unplugging; never strand it under
            # a disabled settings panel owned by the disconnected view.
            if not ready or active:
                self.selection.setParent(self);self.root.insertWidget(0,self.selection);self.selection.show()
            self.current.setEnabled(ready)
            if ready and not active and self.selection.parentWidget() is self:self.dock_selector(self.current)

    def confirm_mapping(self):
        if self.current is None:return True
        return True

    def choose(self,unused=None,*,force=False):
        name=self.choice.currentData()
        if name==self.selected and not force:return
        old=self.worker()
        if (old is not None and busy(old)) or not self.confirm_mapping():
            with QtCore.QSignalBlocker(self.choice):self.choice.setCurrentIndex(self.choice.findData(self.selected))
            return
        previous=self.current
        previous_selection=self.selected
        cached=self.views.get(name);signature=self._pin_signatures.get(name)
        created=None
        try:
            if name is not None:
                worker=self.host.family_tabs['fpga'][name].worker
                if not connected(worker):raise ConnectionError('FPGA 연결을 확인하세요.')
                if cached is None or signature!=worker.profile.document()['pins']:
                    # Keep the old view alive until its replacement is ready.
                    # Each view's provider stays bound to its own FPGA, including
                    # during construction and while another view is selected.
                    with scope(worker.profile):view=self.factory(worker,lambda name=name:self.bindings(name))
                    created=view
                    if hasattr(view,'fpga_selector'):
                        view.fixed_fpga=name;view.fpga_selector.hide()
                    if hasattr(view,'queue'):view.queue.hide()
                    for button in view.findChildren(W.QPushButton):
                        if button.text() in ('Add to Queue','Queue 추가','Queue에 추가'):button.hide()
                    self.views[name]=view;view.hide()
                    self._pin_signatures[name]=worker.profile.document()['pins']
                    # Source files remain explicitly saved by the workflow editor.
                target=self.views[name]
                # Per-FPGA values come from its own config; never copy another FPGA's controls.
                persistence=getattr(self.host,'input_state',None)
                if persistence is not None:persistence.restore()
            else:target=None
            self.selection.setParent(self);self.root.insertWidget(0,self.selection)
            if previous is not None:self.root.removeWidget(previous);previous.hide()
            self.current=target;self.selected=name
            self.empty.setVisible(target is None)
            if target is not None:
                self.root.addWidget(target);target.show();self.dock_selector(target)
        except Exception as exc:
            if created is not None:
                if cached is None:self.views.pop(name,None);self._pin_signatures.pop(name,None)
                else:self.views[name]=cached;self._pin_signatures[name]=signature
                self.selection.setParent(self);self.root.insertWidget(0,self.selection)
                self.current=previous;self.selected=previous_selection
                if previous is not None:
                    self.root.addWidget(previous);previous.show();self.dock_selector(previous)
                self._dispose_view(created)
            self._selection_error=f'{name} · 실험 설정 불러오기 실패: {type(exc).__name__}: {exc}'
            with QtCore.QSignalBlocker(self.choice):self.choice.setCurrentIndex(self.choice.findData(self.selected))
            self.info.setText(self._selection_error)
            self.empty.setText('실험 화면을 열지 못했습니다. 위 오류를 확인하세요.')
            return
        if created is not None and cached is not None:self._dispose_view(cached)
        self._selection_error=None
        self.refresh()

    def _dispose_view(self,view):
        # UI replacement must not cancel the worker's hardware operations.
        for timer in view.findChildren(QtCore.QTimer):timer.stop()
        self.root.removeWidget(view)
        view.hide();view.deleteLater()

    def dock_selector(self,view):
        # Existing sequence settings/results stay intact; place selector above
        # the same left-side settings used by each legacy experiment.
        panel=getattr(view,'settings_panel',None)
        if panel is None:
            for splitter in view.findChildren(W.QSplitter):
                left=splitter.widget(0)
                if isinstance(left,W.QScrollArea):panel=left.widget();break
        layout=panel.layout() if panel is not None and not isinstance(panel,W.QTabWidget) else None
        if isinstance(layout,W.QFormLayout):layout.insertRow(0,self.selection)
        elif isinstance(layout,W.QBoxLayout):layout.insertWidget(0,self.selection)
        else:self.root.insertWidget(0,self.selection)
        mapping=getattr(view,'fpga_role_mapping',None)
        if mapping is not None and layout is not None:
            if isinstance(layout,W.QFormLayout):layout.insertRow(1,mapping)
            elif isinstance(layout,W.QBoxLayout):layout.insertWidget(1,mapping)
        self.selection.show()

    def add_to_queue(self):
        try:
            if not self.confirm_mapping():return
            from labremote.runtime.experiment_jobs import make_job
            worker=self.worker()
            if worker is None or not connected(worker):raise ConnectionError('FPGA를 연결하세요.')
            with scope(worker.profile):job=make_job(self.current,worker,self.title)
            q=self.host.queue_tab
            if q.still_running():raise RuntimeError('Queue를 중지한 뒤 항목을 추가하세요.')
            q.jobs.append(job);q.dirty=True;q.refresh(len(q.jobs)-1)
            self.info.setText('FPGA · 매핑 · 실험 조건을 Queue에 저장했습니다.')
        except Exception as exc:self.info.setText(str(exc))

    def shutdown(self):
        for view in self.views.values():
            if hasattr(view,'shutdown'):view.shutdown()
            for timer in view.findChildren(QtCore.QTimer):timer.stop()


class ExperimentWorkspace(ScrollTabs):
    def __init__(self,host):
        super().__init__();self.host=host;self.slots=[]
        from labremote.experiments.motor_scan.tab import MotorScanTab, SCAN_TABS
        from labremote.experiments.characterization.fluorescence.tab import FluorescenceTab
        from labremote.experiments.characterization.rabi.tab import RabiTab
        from labremote.experiments.characterization.shared.pulse_tab import PulseExperimentTab
        from labremote.experiments.characterization.spam_scan.tab import SpamScanTab
        from labremote.experiments.decay.tab import DecayExperimentTab
        from labremote.experiments.decay.config import MODES, LABELS
        from labremote.experiments.hom.tab import HOMTab
        from labremote.experiments.entanglement.tab import EntanglementTab
        from labremote.experiments.ion_check.tab import IonCheckTab
        from labremote.experiments.micromotion.tab import MicromotionTab
        from labremote.experiments.phase_shifter.hold_tab import EtcTab
        def group(title):
            tabs=ScrollTabs();tabs.settings_group=title;self.addTab(tabs,title);return tabs
        scan=group('Scan')
        for n,(title,axes) in enumerate(SCAN_TABS,1):self.add_slot(scan,title,lambda w,b,n=n:MotorScanTab(w,b,n,host))
        daily=group('Daily characterization')
        for chamber in ('EA','EC'):
            pages=ScrollTabs();pages.settings_group='characterization/'+chamber;daily.addTab(pages,chamber)
            self.add_slot(pages,'Fluorescence',lambda w,b,c=chamber:FluorescenceTab(w,c,host))
            self.add_slot(pages,'Rabi',lambda w,b,c=chamber:RabiTab(w,c,b,host))
            for kind in ('initialization','ramsey','spin_echo','spam'):
                self.add_slot(pages,'Spin Echo' if kind=='spin_echo' else kind.title(),lambda w,b,c=chamber,k=kind:PulseExperimentTab(w,k,c,b,host))
            self.add_slot(pages,'SPAM 2D Scan',lambda w,b,c=chamber:SpamScanTab(w,c,b,host))
        decay=group('Decay')
        for chamber in ('EA','EC'):
            pages=ScrollTabs();pages.settings_group='decay/'+chamber;decay.addTab(pages,chamber)
            for mode in MODES:self.add_slot(pages,LABELS[mode],lambda w,b,c=chamber,m=mode:DecayExperimentTab(w,c,m,host))
        self.add_slot(self,'HOM',lambda w,b:HOMTab(w,host))
        self.add_slot(self,'Entanglement',lambda w,b:EntanglementTab(w,host))
        self.add_slot(self,'Ion Check',lambda w,b:IonCheckTab(w,host))
        self.add_slot(self,'Micromotion',lambda w,b:MicromotionTab(w,b,host))
        self.add_slot(self,'etc',lambda w,b:EtcTab(w,host))
        # Reuse the single existing workflow editor; it has its own FPGA selector.
        if hasattr(host,'workflow_tab'):
            host.device_tabs.removeTab(host.device_tabs.indexOf(host.workflow_tab))
            self.addTab(host.workflow_tab,'Workflow')
        else:
            from .workflow_tab import WorkflowTab
            self.add_slot(self,'Workflow',lambda w,b:WorkflowTab(b,host))
        self.timer=QtCore.QTimer(self);self.timer.setInterval(300);self.timer.timeout.connect(self.refresh);self.timer.start()

    def add_slot(self,tabs,title,factory):
        slot=ExperimentSlot(self.host,title,factory,self)
        slot.settings_id=getattr(tabs,'settings_group','')+'/'+title
        self.slots.append(slot);tabs.addTab(slot,title)
    def refresh(self):
        for slot in self.slots:slot.refresh()
    def still_running(self):
        return any(getattr(v,'still_running',lambda:False)() for s in self.slots for v in s.views.values())
    def confirm_close(self):
        return all(s.confirm_mapping() and all(getattr(v,'confirm_close',lambda:True)() for v in s.views.values()) for s in self.slots)
    def shutdown(self):
        self.timer.stop()
        for slot in self.slots:slot.shutdown()
