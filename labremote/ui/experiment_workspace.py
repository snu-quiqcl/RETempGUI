"""Shared experiment pages select a connected FPGA without moving running jobs."""
from pathlib import Path
from PyQt5 import QtCore, QtWidgets as W
from labremote.devices.fpga.mapping import scope
from .input_state import INPUTS, value_of, apply_value
from .fpga_mapping import RoleMapping


def connected(worker):
    return worker.ps is not None and not worker.connection_error and not worker._closing and not worker._disconnecting


def busy(worker):
    return (getattr(worker,'_fpga_owner',None) is not None or worker.has_requests()
            or worker.waveform_runner.running() or any(t.running() for t in worker._background_tasks))


def fields(root):
    """Attribute paths survive reparenting and have no dependence on pin names."""
    result={};seen=set()
    def walk(value,key):
        if isinstance(value,W.QWidget):
            if id(value) in seen or (value is not root and not root.isAncestorOf(value)):return
            seen.add(id(value))
            if isinstance(value,RoleMapping):return
            if isinstance(value,INPUTS):
                if value_of(value) is not None and not key.endswith('/source'):result[key]=value
                return
            for attr,child in vars(value).items():
                if not attr.startswith('_') and attr not in ('host','owner','parent'):walk(child,key+'/'+attr)
        elif isinstance(value,dict):
            for name,child in value.items():walk(child,key+'/'+str(name))
        elif isinstance(value,(list,tuple)):
            for i,child in enumerate(value):walk(child,key+'/'+str(i))
    walk(root,'')
    return result


class ExperimentSlot(W.QWidget):
    def __init__(self,host,title,factory,parent=None):
        super().__init__(parent);self.host=host;self.title=title;self.factory=factory
        self.views={};self.selected=None;self.current=None;self._refreshing=False;self._pin_signatures={}
        self.root=W.QVBoxLayout(self)
        self.selection=W.QGroupBox('FPGA 선택');form=W.QVBoxLayout(self.selection)
        self.choice=W.QComboBox();self.choice.setProperty('persistInput',False);form.addWidget(self.choice)
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

    def bindings(self):
        return {key:value for key,value in self.host._bindings().items()
                if value[0]!='fpga' or value[1].worker.name==self.selected}

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
        if ready and self.current is not None and not active and self._pin_signatures.get(self.selected)!=w.profile.document()['pins']:
            self.choose(force=True)
            return
        self.queue_button.setEnabled(ready and self.current is not None and not self.host.queue_tab.still_running())
        if w is None:self.info.setText('연결된 장비만 선택할 수 있습니다.')
        else:self.info.setText(('연결됨' if ready else '연결 끊김 · 재연결 후 실행하세요.')+
                              (' · 장비 사용 중' if active else '')+'\nFPGA 전환 시 실험 조건은 유지됩니다.')
        if self.current is not None:
            for mapping in self.current.findChildren(RoleMapping):
                if not mapping.dirty() and mapping._loaded_document!=mapping.worker.profile.document():mapping.refresh()
                mapping.setEnabled(not active)
            # Keep the selector usable after unplugging; never strand it under
            # a disabled settings panel owned by the disconnected view.
            if not ready or active:
                self.selection.setParent(self);self.root.insertWidget(0,self.selection);self.selection.show()
            self.current.setEnabled(ready)
            if ready and not active and self.selection.parentWidget() is self:self.dock_selector(self.current)

    def confirm_mapping(self):
        if self.current is None:return True
        for mapping in self.current.findChildren(RoleMapping):
            if not mapping.dirty():continue
            answer=W.QMessageBox.question(self,'핀 매핑','변경한 핀 매핑을 저장할까요?',W.QMessageBox.Save|W.QMessageBox.Discard|W.QMessageBox.Cancel)
            if answer==W.QMessageBox.Cancel:return False
            if answer==W.QMessageBox.Save:
                if not mapping.apply():return False
            else:mapping.refresh()
        return True

    def choose(self,unused=None,*,force=False):
        name=self.choice.currentData()
        if name==self.selected and not force:return
        old=self.worker()
        if (old is not None and busy(old)) or not self.confirm_mapping():
            with QtCore.QSignalBlocker(self.choice):self.choice.setCurrentIndex(self.choice.findData(self.selected))
            return
        settings={k:value_of(w) for k,w in fields(self.current).items()} if self.current is not None else {}
        # Device names/routes and auto-generated data paths belong to the target.
        routing=('inputs','outputs','roles','selectors','mapping','mapping_fields','channel','pmt_pin','trg_pin','trigger_pin','counter_pin','directory','file_picker')
        settings={k:v for k,v in settings.items() if not any(part in routing or 'selector' in part for part in k.split('/'))}
        previous=self.current
        try:
            if name is not None:
                worker=self.host.family_tabs['fpga'][name].worker
                if not connected(worker):raise ConnectionError('FPGA 연결을 확인하세요.')
                if name in self.views and self._pin_signatures.get(name)!=worker.profile.document()['pins']:
                    stale=self.views.pop(name)
                    self.selection.setParent(self)
                    for timer in stale.findChildren(QtCore.QTimer):timer.stop()
                    stale.hide();stale.deleteLater()
                if name not in self.views:
                    with scope(worker.profile):view=self.factory(worker,self.bindings)
                    if hasattr(view,'fpga_selector'):
                        view.fixed_fpga=name;view.fpga_selector.hide()
                    if hasattr(view,'queue'):view.queue.hide()
                    for button in view.findChildren(W.QPushButton):
                        if button.text() in ('Add to Queue','Queue 추가','Queue에 추가'):button.hide()
                    self.views[name]=view;view.hide()
                    self._pin_signatures[name]=worker.profile.document()['pins']
                    # Source files remain explicitly saved by the workflow editor.
                target=self.views[name]
                for key,widget in fields(target).items():
                    if key in settings:apply_value(widget,settings[key])
            else:target=None
            self.selection.setParent(self);self.root.insertWidget(0,self.selection)
            if previous is not None:self.root.removeWidget(previous);previous.hide()
            self.current=target;self.selected=name
            self.empty.setVisible(target is None)
            if target is not None:
                self.root.addWidget(target);target.show();self.dock_selector(target)
                for mapping in target.findChildren(RoleMapping):mapping.refresh()
        except Exception as exc:
            self.info.setText(str(exc))
            with QtCore.QSignalBlocker(self.choice):self.choice.setCurrentIndex(self.choice.findData(self.selected))
            return
        self.refresh()

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


class ExperimentWorkspace(W.QTabWidget):
    def __init__(self,host):
        super().__init__();self.host=host;self.slots=[]
        from .motor_scan_tab import MotorScanTab,SCAN_TABS
        from .daily_characterization import FluorescenceTab
        from .rabi_tab import RabiTab
        from .pulse_experiment_tab import PulseExperimentTab
        from .decay_tab import DecayExperimentTab
        from labremote.decay.config import MODES,LABELS
        from .hom_tab import HOMTab
        from .entanglement_tab import EntanglementTab
        from .ion_check_tab import IonCheckTab
        from .micromotion_tab import MicromotionTab
        from labremote.phase_shifter.hold_tab import EtcTab
        def group(title):
            tabs=W.QTabWidget();self.addTab(tabs,title);return tabs
        scan=group('Scan')
        for n,(title,axes) in enumerate(SCAN_TABS,1):self.add_slot(scan,title,lambda w,b,n=n:MotorScanTab(w,b,n,host))
        daily=group('Daily characterization')
        for chamber in ('EA','EC'):
            pages=W.QTabWidget();daily.addTab(pages,chamber)
            self.add_slot(pages,'Fluorescence',lambda w,b,c=chamber:FluorescenceTab(w,c,host))
            self.add_slot(pages,'Rabi',lambda w,b,c=chamber:RabiTab(w,c,b,host))
            for kind in ('initialization','ramsey','spam'):
                self.add_slot(pages,kind.title(),lambda w,b,c=chamber,k=kind:PulseExperimentTab(w,k,c,b,host))
        decay=group('Decay')
        for chamber in ('EA','EC'):
            pages=W.QTabWidget();decay.addTab(pages,chamber)
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
        slot=ExperimentSlot(self.host,title,factory,self);self.slots.append(slot);tabs.addTab(slot,title)
    def refresh(self):
        for slot in self.slots:slot.refresh()
    def still_running(self):
        return any(getattr(v,'still_running',lambda:False)() for s in self.slots for v in s.views.values())
    def confirm_close(self):
        return all(s.confirm_mapping() and all(getattr(v,'confirm_close',lambda:True)() for v in s.views.values()) for s in self.slots)
    def shutdown(self):
        self.timer.stop()
        for slot in self.slots:slot.shutdown()
