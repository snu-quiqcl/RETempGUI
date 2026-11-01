"""Experiment home and equipment selection. Device APIs and workflow semantics stay unchanged."""
from collections import deque
from copy import deepcopy
from pathlib import Path
from PyQt5 import QtCore,QtWidgets
from labremote.api.devices import DeviceAPI
from labremote.config import equipment
from .detail_window import DetailWindow
from .equipment_configuration import EquipmentConfigurationDialog

class ExperimentShellMixin:
    def setup_experiment_shell(self,server_panel):
        self.profile_errors={};self.connection_queue=deque();self.connection_handle=None;self.connection_entry=None
        self._equipment_candidates=[];self.profile_dirty=False;self.profile_path=None;self.detail_windows={}
        self.equipment_profile=equipment.defaults(self.cfg)
        requested=self.cfg.get('equipment_configuration')
        startup_error=''
        try:
            path=Path(requested) if requested else equipment.LOCAL
            if path.exists():self.equipment_profile=equipment.load(path);self.profile_path=path
            elif requested:raise ValueError('Configuration file not found: '+str(path))
            else:equipment.save(path,self.equipment_profile);self.profile_path=path
        except Exception as exc:
            # A missing/broken selection must not silently connect a different set.
            self.equipment_profile={'schema_version':1,'name':'구성 파일 확인 필요','devices':[]};startup_error=str(exc)
        self.cfg['equipment_configuration']=str(self.profile_path) if self.profile_path else ''
        self.ccd_tab.apply_display_config(self.equipment_profile.get('ccd_display',{}))
        # Reparent existing widgets. No replacement workers, connections, or operations.
        detailed=[('RF',self.rf_tabs),('미라',self.mira_tabs),('CCD',self.ccd_tab),('FPGA',self.family_subtabs['fpga']),('오실로스코프',self.oscillo_tabs),('기타',self.others_tabs)]
        for title,widget in detailed:
            index=self.device_tabs.indexOf(widget)
            if index>=0:self.device_tabs.removeTab(index)
            window=DetailWindow(title,widget,self);self.detail_windows[title]=window;self.device_tabs.detail_windows[widget]=window
        self.home=QtWidgets.QWidget();root=QtWidgets.QVBoxLayout(self.home);root.setSpacing(14)
        heading=QtWidgets.QHBoxLayout();heading.addWidget(QtWidgets.QLabel('실험 준비'),1)
        settings=QtWidgets.QPushButton('연결 설정 / 장비 목록');heading.addWidget(settings);root.addLayout(heading)
        self.connection_settings_window=DetailWindow('연결 설정',server_panel,self);settings.clicked.connect(self.connection_settings_window.open)
        box=QtWidgets.QGroupBox('Configuration');line=QtWidgets.QHBoxLayout(box)
        self.profile_label=QtWidgets.QLabel();line.addWidget(self.profile_label,1)
        self.profile_buttons=[]
        for title,callback in [('불러오기',self.load_equipment),('편집',self.edit_equipment),('저장',self.save_equipment),('다른 이름으로 저장',lambda:self.save_equipment(True))]:
            button=QtWidgets.QPushButton(title);button.clicked.connect(lambda _,fn=callback:fn());line.addWidget(button);self.profile_buttons.append(button)
        root.addWidget(box)
        box=QtWidgets.QGroupBox('장비 연결');grid=QtWidgets.QGridLayout(box)
        connect_all=QtWidgets.QPushButton('전체 연결');connect_all.clicked.connect(lambda:self.connect_equipment());grid.addWidget(connect_all,0,1)
        self.disconnect_all_button=QtWidgets.QPushButton('연결 해제');self.disconnect_all_button.clicked.connect(self.disconnect_equipment);grid.addWidget(self.disconnect_all_button,0,2)
        self.group_labels={};self.group_buttons={}
        for row,group in enumerate(equipment.GROUPS,1):
            grid.addWidget(QtWidgets.QLabel(group),row,0);label=QtWidgets.QLabel();grid.addWidget(label,row,1);self.group_labels[group]=label
            button=QtWidgets.QPushButton('연결 / 재연결');button.clicked.connect(lambda _,g=group:self.connect_equipment(g));grid.addWidget(button,row,2);self.group_buttons[group]=button
        self.connect_all_button=connect_all;root.addWidget(box)
        self.shell_message=QtWidgets.QLabel(startup_error or '구성을 확인한 뒤 장비를 연결하세요. 연결만으로 실험 설정을 적용하지 않습니다.');self.shell_message.setWordWrap(True);root.addWidget(self.shell_message)
        row=QtWidgets.QHBoxLayout();self.activity_label=QtWidgets.QLabel('대기 중');row.addWidget(self.activity_label,1)
        self.cancel_tasks_button=QtWidgets.QPushButton('작업 중단 / 종료 정리');self.cancel_tasks_button.clicked.connect(self.stop_experiment_tasks);row.addWidget(self.cancel_tasks_button);root.addLayout(row)
        root.addStretch()
        self.device_tabs.insertTab(0,self.home,'메인')
        self.device_tabs.setTabText(self.device_tabs.indexOf(self.workflow_tab),'Workflow')
        self.monitor_placeholder=QtWidgets.QWidget();monitor=QtWidgets.QVBoxLayout(self.monitor_placeholder);monitor.addWidget(QtWidgets.QLabel('Monitor · 구성 예정'));monitor.addStretch();self.device_tabs.addTab(self.monitor_placeholder,'Monitor');self.device_tabs.setCurrentWidget(self.home)
        self.equipment_timer=QtCore.QTimer(self);self.equipment_timer.setInterval(200);self.equipment_timer.timeout.connect(self.refresh_experiment_home);self.equipment_timer.start()
        self.ccd_tab.oven_panel.psu_name.clear();self.ccd_tab.oven_panel.relay_name.clear()
        for entry in self.equipment_profile['devices']:
            if entry['enabled'] or entry['family'] in ('oven_psu','oven_relay'):self.ensure_equipment(entry)
        self.device_menu=self.menuBar().addMenu('장비')
        self.device_menu.aboutToShow.connect(self.populate_device_menu)
        self._observed_workers=set();self.refresh_experiment_home()

    def populate_device_menu(self):
        self.device_menu.clear()
        for title,window in self.detail_windows.items():
            menu=self.device_menu.addMenu(title)
            action=menu.addAction(title+' 창 열기');action.triggered.connect(window.open)
            for family,panels in self.family_tabs.items():
                if equipment.FAMILY_GROUP.get(family)!=title:continue
                for name in panels:
                    action=menu.addAction(family+' / '+name)
                    action.triggered.connect(lambda _,f=family,n=name:self.open_device_control(f,n))
            if title=='기타':
                action=menu.addAction('Flipper / 셔터');action.triggered.connect(lambda:self.open_device_control('flip'))
                for name in self.flip_tab.workers:
                    action=menu.addAction('Flipper / '+name);action.triggered.connect(lambda _,n=name:self.open_device_control('flip',n))
            if title=='CCD':
                action=menu.addAction('오븐 / 셔터');action.triggered.connect(lambda:self.open_device_control('oven_psu'))

    def open_device_control(self,family,name=None):
        if self._closing:return
        title='CCD' if family in ('oven_psu','oven_relay') else equipment.FAMILY_GROUP[family]
        window=self.detail_windows[title];window.open()
        if family=='flip':
            self.others_tabs.setCurrentWidget(self.flip_tab)
            if name in self.flip_tab.cards:window.scroll.ensureWidgetVisible(self.flip_tab.cards[name]['box'])
        elif family in ('oven_psu','oven_relay'):
            window.scroll.ensureWidgetVisible(self.ccd_tab.oven_panel)
        elif name is not None:
            tabs=self.family_subtabs[family];panel=self.family_tabs[family][name]
            if family=='motors':
                self.others_tabs.setCurrentWidget(self.motor_tab);window.scroll.ensureWidgetVisible(panel.target);panel.target.setFocus()
            else:
                tabs.setCurrentWidget(panel)
                parent={'RF':self.rf_tabs,'미라':self.mira_tabs,'오실로스코프':self.oscillo_tabs,'기타':self.others_tabs}.get(title)
                if parent is not None:parent.setCurrentWidget(tabs)

    def register_equipment(self,family,name):
        try:
            document=deepcopy(self.equipment_profile)
            if any(e['family']==family and e['name']==name for e in document['devices']):raise ValueError('이미 등록된 장비입니다. Configuration에서 사용 여부를 변경하세요.')
            document['devices'].append(dict(family=family,name=name,group=equipment.FAMILY_GROUP[family],enabled=True))
            self.apply_equipment(document)
        except Exception as exc:self.shell_message.setText(str(exc))

    def selected_equipment(self,group=None):
        return [e for e in self.equipment_profile['devices'] if e['enabled'] and (group is None or e['group']==group)]

    def equipment_enabled(self,family,name):
        if not hasattr(self,'equipment_profile'):return True
        return any(e['family']==family and e['name']==name for e in self.selected_equipment())

    def ensure_equipment(self,entry):
        family,name=entry['family'],entry['name']
        if family in self.family_tabs:self._add_family(family,name)
        elif family=='flip':self.flip_tab._add_worker(name)
        elif family=='oven_psu':self.ccd_tab.oven_panel.psu_name.setText(name)
        elif family=='oven_relay':self.ccd_tab.oven_panel.relay_name.setText(name)

    def equipment_worker(self,entry):
        family,name=entry['family'],entry['name']
        if family in self.family_tabs:
            panel=self.family_tabs[family].get(name);return panel.worker if panel else None
        return {'ccd':self.ccd_tab.worker,'oven_psu':self.ccd_tab.oven_panel.psu,'oven_relay':self.ccd_tab.oven_panel.relays,'flip':self.flip_tab.workers.get(name)}.get(family)

    def worker_busy(self,worker):
        if worker is None:return False
        if worker is self.ccd_tab.worker:
            with worker._handles_lock:return bool(worker._handles)
        return worker.has_requests() if hasattr(worker,'has_requests') else False

    def equipment_connected(self,entry):
        worker=self.equipment_worker(entry)
        if worker is None:return False
        if entry['family']=='ccd':return worker.available
        active=getattr(worker,'_active',None)
        if active is not None and active.action=='CONNECT' and not active.done.is_set():return False
        if worker.ps is None or worker.connection_error or getattr(worker,'io_fault',False):return False
        if entry['family']=='fpga':return True
        identity=worker._execution_device
        target=entry['name']
        if entry['family']=='motors':target=self.family_tabs['motors'][entry['name']].target.text().strip()
        return identity==(*self._endpoint(),target)

    def active_experiment_tasks(self):
        tasks={t for panel in self._panels() for t in getattr(panel.worker,'_background_tasks',())}
        return [t for t in tasks if t.running()]

    def selection_editable(self):
        if self._closing or self.connection_queue or self.connection_handle is not None or self.workflow_tab.still_running() or self.active_experiment_tasks():return False
        if not self.rescan_btn.isEnabled() or self.flip_tab._discovering:return False
        return not any(self.worker_busy(p.worker) or getattr(p.worker,'available',False) or getattr(p.worker,'ps',None) is not None for p in self._panels())

    def apply_equipment(self,document,path=None):
        validated=equipment.validate(document)
        if not self.selection_editable():raise RuntimeError('구성 변경 전 작업을 종료하고 장비 연결을 해제하세요.')
        # Validate the entire file before modifying any selection.
        self.ccd_tab.oven_panel.psu_name.clear();self.ccd_tab.oven_panel.relay_name.clear()
        for entry in validated['devices']:
            if entry['enabled'] or entry['family'] in ('oven_psu','oven_relay'):self.ensure_equipment(entry)
        self.ccd_tab.apply_display_config(validated.get('ccd_display',{}))
        self.equipment_profile=validated;self.profile_path=Path(path) if path else self.profile_path
        self.cfg['equipment_configuration']=str(self.profile_path) if self.profile_path else ''
        self.profile_dirty=path is None;self.profile_errors.clear();self.refresh_experiment_home()

    def load_equipment(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'장비 구성 불러오기',str(self.profile_path or equipment.LOCAL),'Equipment configuration (*.json)')
        if not path:return
        if self.profile_dirty and QtWidgets.QMessageBox.question(self,'저장되지 않은 구성','현재 구성의 저장되지 않은 변경을 버리고 불러올까요?')!=QtWidgets.QMessageBox.Yes:return
        try:self.apply_equipment(equipment.load(path),path);self.shell_message.setText('구성 불러오기 완료 · 장비 연결은 별도로 실행합니다.')
        except Exception as exc:self.shell_message.setText(str(exc))

    def edit_equipment(self):
        if not self.selection_editable():self.shell_message.setText('구성 편집 전 작업 종료 및 연결 해제가 필요합니다.');return
        dialog=EquipmentConfigurationDialog(self.equipment_profile,self._equipment_candidates,self)
        if dialog.exec_()==QtWidgets.QDialog.Accepted:
            try:self.apply_equipment(dialog.document());self.shell_message.setText('구성 적용 완료 · 저장 버튼으로 파일에 보관하세요.')
            except Exception as exc:self.shell_message.setText(str(exc))

    def save_equipment(self,save_as=False):
        path=self.profile_path
        if save_as or path is None or not path.name.endswith('.local.json'):
            chosen,_=QtWidgets.QFileDialog.getSaveFileName(self,'장비 구성 저장',str(path.with_name(path.stem+'.local.json') if path and not path.name.endswith('.local.json') else path or equipment.LOCAL),'Local configuration (*.local.json)')
            if not chosen:return False
            path=Path(chosen)
            if not path.name.endswith('.local.json'):path=path.with_name(path.stem+'.local.json')
        try:
            equipment.save(path,self.equipment_profile);self.profile_path=path;self.cfg['equipment_configuration']=str(path);self.profile_dirty=False
            self.shell_message.setText('구성 저장 완료');self.refresh_experiment_home();return True
        except Exception as exc:self.shell_message.setText(str(exc));return False

    def connect_equipment(self,group=None):
        if self._closing or self.workflow_tab.still_running() or self.active_experiment_tasks():self.shell_message.setText('실행 중인 작업 종료 후 연결하세요.');return
        if self.connection_queue or self.connection_handle is not None:return
        self.connection_queue=deque(self.selected_equipment(group));self.shell_message.setText('선택한 장비를 순서대로 연결합니다. 실패한 장비는 재연결 버튼으로 다시 시도하세요.')
        self.pump_connections()

    def connect_equipment_entry(self,entry):
        self.ensure_equipment(entry);family,name=entry['family'],entry['name'];worker=self.equipment_worker(entry)
        if family=='ccd':
            if not worker.isRunning():worker._closing=False;worker.start()
            return self.ccd_tab.api.connect(**self.ccd_tab.settings())
        if family=='fpga':return self.family_tabs[family][name]._connect()
        if family=='motors':return self.family_tabs[family][name].api.connect_motor(*self._endpoint(),self.family_tabs[family][name].target.text().strip())
        if family=='flip':
            from labremote.devices.flip.settings import save_endpoint
            save_endpoint(*self._endpoint())
        return DeviceAPI(worker).connect(*self._endpoint(),name)

    def pump_connections(self):
        if self._closing:return
        if self.connection_handle is not None:
            handle=self.connection_handle
            if not handle.done.is_set():return
            entry=self.connection_entry;key=(entry['family'],entry['name'])
            if handle.error:self.profile_errors[key]=str(handle.error)
            elif entry['family']=='flip':
                # CONNECT has already verified server registration and MFF identity.
                name=entry['name'];flip=self.flip_tab
                flip._listed_endpoint=flip._request_endpoint=self._endpoint()
                if name not in flip._server_names:flip._server_names.append(name)
                if flip.selected.findText(name)<0:flip.selected.addItem(name)
                if flip.routing.available_names is not None:flip.routing.available_names.add(name)
            self.connection_handle=self.connection_entry=None
        if self.workflow_tab.still_running() or self.active_experiment_tasks():
            self.connection_queue.clear();return
        while self.connection_queue:
            entry=self.connection_queue.popleft();key=(entry['family'],entry['name'])
            if self.equipment_connected(entry):continue
            if self.worker_busy(self.equipment_worker(entry)):
                self.profile_errors[key]='장비 작업 중 · 완료 후 재연결';continue
            try:
                self.profile_errors.pop(key,None);self.connection_entry=entry;self.connection_handle=self.connect_equipment_entry(entry);return
            except Exception as exc:self.profile_errors[key]=str(exc);self.connection_entry=None

    def disconnect_equipment(self):
        if self.workflow_tab.still_running() or self.active_experiment_tasks():self.shell_message.setText('작업 중단 / 종료 정리 완료 후 연결을 해제하세요.');return
        self.connection_queue.clear()
        if self.connection_handle is not None and not self.connection_handle.done.is_set():self.shell_message.setText('현재 연결 요청 완료 후 다시 연결 해제하세요.');return
        seen=set()
        for panel in self._panels():
            worker=panel.worker
            if id(worker) in seen:continue
            seen.add(id(worker))
            if self.worker_busy(worker):continue
            if worker is self.ccd_tab.worker:
                if worker.available:self.ccd_tab.api.disconnect()
            elif getattr(worker,'ps',None) is not None:DeviceAPI(worker).disconnect()
        self.shell_message.setText('연결 해제 요청 · 출력 OFF 명령과는 별개입니다. 기존 종료 workflow를 먼저 실행하세요.')

    def stop_experiment_tasks(self):
        self.connection_queue.clear();self.workflow_tab.cancel()
        for task in self.active_experiment_tasks():task.cancel()
        self.shell_message.setText('작업 중단 요청 · 진행 중인 명령 반환과 기존 종료 정리를 기다립니다.')

    def show_shell_failure(self,*args):
        if not self._closing:self.shell_message.setText(' · '.join(str(a) for a in args))

    def refresh_experiment_home(self):
        from .connection_status import connection_color
        if self._closing:return
        self.pump_connections()
        for panel in self._panels():
            worker=panel.worker
            if id(worker) not in self._observed_workers and hasattr(worker,'failure'):
                self._observed_workers.add(id(worker))
                worker.failure.connect(self.show_shell_failure)
        selected=self.selected_equipment();busy=bool(self.connection_queue or self.connection_handle is not None)
        active=self.workflow_tab.still_running() or bool(self.active_experiment_tasks())
        for group,label in self.group_labels.items():
            entries=[e for e in selected if e['group']==group];connected=sum(self.equipment_connected(e) for e in entries)
            failed=[e['name'] for e in entries if not self.equipment_connected(e) and (e['family'],e['name']) in self.profile_errors]
            label.setText(f'{connected} / {len(entries)} 연결'+(f' · {len(failed)}대 실패' if failed else ''))
            label.setToolTip('\n'.join(e['name']+': '+('연결됨' if self.equipment_connected(e) else self.profile_errors.get((e['family'],e['name']),'미연결')) for e in entries))
            connection_color(self.group_buttons[group], 'connected' if entries and connected==len(entries) else 'partial' if connected else 'error' if failed else 'disconnected')
            from labremote.runtime.auto_monitor import AUTO_MONITOR, endpoint
            if any((w:=self.equipment_worker(e)) is not None and endpoint(w) in AUTO_MONITOR.blocked for e in entries):
                label.setText(label.text()+' · 자동 조회 중지 (연결 해제 후 재연결)')
            self.group_buttons[group].setEnabled(bool(entries) and not busy and not active)
        connected_total=sum(self.equipment_connected(e) for e in selected)
        connection_color(self.connect_all_button, 'connected' if selected and connected_total==len(selected) else 'partial' if connected_total else 'disconnected')
        self.connect_all_button.setEnabled(bool(selected) and not busy and not active);self.disconnect_all_button.setEnabled(not active and not busy)
        self.profile_label.setText(self.equipment_profile['name']+(' *' if self.profile_dirty else ''));self.profile_label.setToolTip(str(self.profile_path or '저장되지 않은 구성'))
        self.profile_buttons[0].setEnabled(self.selection_editable());self.profile_buttons[1].setEnabled(self.selection_editable())
        self.activity_label.setText('연결 중: '+self.connection_entry['name'] if self.connection_entry else 'Workflow: '+self.workflow_tab.status.text() if self.workflow_tab.still_running() else '실행 중: '+', '.join(t.label for t in self.active_experiment_tasks()) if self.active_experiment_tasks() else '대기 중')
        selected_workers={id(self.equipment_worker(e)) for e in selected}
        extra={id(p.worker) for p in self._panels() if id(p.worker) not in selected_workers and (getattr(p.worker,'ps',None) is not None or getattr(p.worker,'available',False))}
        if extra:self.activity_label.setText(self.activity_label.text()+f' · 구성 외 수동 연결 {len(extra)}대')
        self.cancel_tasks_button.setEnabled(active or busy)

    def close_equipment_windows(self):
        self.equipment_timer.stop()
        for window in [*self.detail_windows.values(),self.connection_settings_window]:
            window.allow_close=True;window.close()
