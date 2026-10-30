"""RF device tabs and the shared workflow editor."""
import argparse
import sys
from PyQt5 import QtCore, QtWidgets
from labremote.ui.theme import apply_theme
from labremote.config.settings import load_settings, save_settings
from labremote.config.device_config import configured_instrument_names
from labremote.devices.windfreak.tab import WindfreakTab
from labremote.ui.workflow_tab import WorkflowTab
from labremote.ui.rf_device_tab import RFDeviceTab
from labremote.devices.ds1052e.tab import DS1052ETab
from labremote.devices.mso7054.tab import MSO7054Tab
from labremote.ui.equipment_tab import EquipmentTab
from labremote.ui.auxiliary_tab import AuxiliaryTab
from labremote.runtime.discovery import DiscoveryWorker
from labremote.runtime.recording import set_detailed_logging

class WheelToMainScroll(QtCore.QObject):
    """Prevent mouse wheel from changing spinbox values; scroll whole window."""
    def __init__(self, scroll, content, parent=None):
        super().__init__(parent)
        self.scroll, self.content = scroll, content

    def eventFilter(self, watched, ev):
        if ev.type() != QtCore.QEvent.Wheel or (ev.modifiers() & QtCore.Qt.ControlModifier):
            return False
        if not isinstance(watched, QtWidgets.QWidget):
            return False
        if watched != self.content and not self.content.isAncestorOf(watched):
            return False
        ancestor = watched
        while ancestor is not None and ancestor != self.content:
            if ancestor.property('handlesWheelZoom'):
                return False
            if isinstance(ancestor, QtWidgets.QAbstractScrollArea):
                bar = ancestor.verticalScrollBar()
                if bar is not None and bar.maximum() > bar.minimum():
                    return False
            ancestor = ancestor.parentWidget()
        bar = self.scroll.verticalScrollBar()
        if bar.maximum() <= bar.minimum():
            return False
        delta = ev.pixelDelta().y() or ev.angleDelta().y() / 120 * max(24, bar.singleStep()*3)
        if delta:
            bar.setValue(bar.value()-int(round(delta)))
            ev.accept()
            return True
        return False



class Window(QtWidgets.QMainWindow):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self._closing = False
        self._workers_shutdown = False
        self.dynamic_windfreak_tabs = {}
        self.family_tabs = {"windfreak": self.dynamic_windfreak_tabs, "sg384": {}, "anapico": {}, "dds4": {}, "ds1052e": {}, 'mso7054':{}, 'thermotek':{}, 'keithley':{}, 'osa':{}, 'mdt':{}, 'fpga':{}, 'motors':{}}
        self.setWindowTitle('RETempUI V1.00 | RF + oscillo + local CCD')
        self.resize(1370, 920)
        menu = self.menuBar().addMenu('Operation 기록')
        action = menu.addAction('Operation get/set 상세 로그 저장')
        action.setCheckable(True)
        action.setChecked(cfg.get('operation_detailed_logging', False))
        set_detailed_logging(action.isChecked())
        action.toggled.connect(self._logging)
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        server = QtWidgets.QGroupBox('InstrumentServer · Server-owned instruments')
        row = QtWidgets.QHBoxLayout(server)
        self.discovery_host = QtWidgets.QLineEdit(cfg['server_host'])
        self.discovery_port = QtWidgets.QSpinBox(); self.discovery_port.setRange(1,65535)
        self.discovery_port.setValue(cfg['server_port'])
        self.rescan_btn = QtWidgets.QPushButton('Rescan server devices')
        self.manual_name = QtWidgets.QLineEdit(); self.manual_name.setPlaceholderText('Instrument name')
        self.manual_family = QtWidgets.QComboBox(); self.manual_family.addItems(list(self.family_tabs))
        add = QtWidgets.QPushButton('Add device')
        for w in (QtWidgets.QLabel('Host'),self.discovery_host,QtWidgets.QLabel('Port'),self.discovery_port,self.rescan_btn,self.manual_family,self.manual_name,add): row.addWidget(w)
        layout.addWidget(server)
        self.device_tabs = QtWidgets.QTabWidget()
        self.windfreak_subtabs = QtWidgets.QTabWidget()
        self.rf_tabs=QtWidgets.QTabWidget()
        self.oscillo_tabs=QtWidgets.QTabWidget()
        self.device_tabs.addTab(self.rf_tabs,'RF')
        self.device_tabs.addTab(self.oscillo_tabs,'oscillo')
        self.rf_tabs.addTab(self.windfreak_subtabs, 'Windfreak')
        self.family_subtabs = {'windfreak': self.windfreak_subtabs}
        for family,title in [('sg384','SG384'),('anapico','AnaPico'),('dds4','DDS / AD9912')]:
            tabs=QtWidgets.QTabWidget(); self.family_subtabs[family]=tabs
            self.rf_tabs.addTab(tabs,title)
        self.ds1052e_subtabs=QtWidgets.QTabWidget()
        self.family_subtabs['ds1052e']=self.ds1052e_subtabs
        self.oscillo_tabs.addTab(self.ds1052e_subtabs,'DS1052E')
        mso_tabs=QtWidgets.QTabWidget();self.family_subtabs['mso7054']=mso_tabs
        self.oscillo_tabs.addTab(mso_tabs,'MSO7054')
        self.mira_tabs=QtWidgets.QTabWidget();self.others_tabs=QtWidgets.QTabWidget()
        self.device_tabs.addTab(self.mira_tabs,'mira');self.device_tabs.addTab(self.others_tabs,'others')
        for family,title,parent in [('thermotek','THERMOTEK',self.mira_tabs),('keithley','Keithley',self.others_tabs),('osa','OSA',self.mira_tabs),('mdt','MDT',self.mira_tabs),('fpga','FPGA',self.others_tabs)]:
            tabs=QtWidgets.QTabWidget();self.family_subtabs[family]=tabs;parent.addTab(tabs,title)
        from labremote.ui.motor_tab import MotorTab
        self.motor_tab=MotorTab(self,endpoint=self._endpoint);self.family_subtabs['motors']=self.motor_tab
        self.others_tabs.addTab(self.motor_tab,'Motor')
        self.workflow_tab = WorkflowTab(self._bindings, self)
        self.device_tabs.addTab(self.workflow_tab, 'workflow')
        layout.addWidget(self.device_tabs)
        self.log = QtWidgets.QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(120)
        layout.addWidget(self.log)
        from labremote.devices.ccd.tab import CCDTab
        self.ccd_tab = CCDTab(self, cfg.get('ccd_options', {}), endpoint=self._endpoint)
        self.ccd_tab.log_message.connect(self.log.appendPlainText)
        self.device_tabs.insertTab(self.device_tabs.indexOf(self.workflow_tab), self.ccd_tab, 'CCD')
        self.scroll = QtWidgets.QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setWidget(content)
        self.setCentralWidget(self.scroll)
        self.wheel_filter = WheelToMainScroll(self.scroll, content, self)
        QtWidgets.QApplication.instance().installEventFilter(self.wheel_filter)
        self.discovery_worker = DiscoveryWorker(self)
        self.discovery_worker.devices_found.connect(self._discovered)
        self.discovery_worker.failure.connect(self._discovery_error)
        self.discovery_worker.start()
        self.rescan_btn.clicked.connect(self._scan)
        add.clicked.connect(lambda: self._add_family(self.manual_family.currentText(),self.manual_name.text().strip()))
        for name in (*configured_instrument_names('windfreak'), *cfg.get('windfreak_names', [])):
            self._add(name)
        for family in ('sg384','anapico','dds4','ds1052e','mso7054','thermotek','keithley','osa','mdt','fpga','motors'):
            for name in (*configured_instrument_names(family), *cfg.get(family+'_names', [])):
                self._add_family(family,name)
        self.close_timer = QtCore.QTimer(self); self.close_timer.timeout.connect(self._close_ready)

    def _logging(self, enabled):
        self.cfg['operation_detailed_logging'] = enabled
        set_detailed_logging(enabled)

    def _endpoint(self): return self.discovery_host.text().strip(), self.discovery_port.value()

    def _scan(self):
        self.rescan_btn.setEnabled(False)
        self.discovery_worker.scan(*self._endpoint())

    def _discovery_error(self, message):
        self.rescan_btn.setEnabled(True)
        self.log.appendPlainText(message)

    def _discovered(self, devices):
        self.rescan_btn.setEnabled(True)
        if self._closing: return
        for d in devices:
            family={'windfreak_synthhd':'windfreak','srs_sg384':'sg384','anapico_apsyn420':'anapico','dds4_ad9912_vva':'dds4','rigol_ds1052e':'ds1052e','rigol_mso7054':'mso7054','thermotek_t257p':'thermotek','keithley_2231a':'keithley','yokogawa_aq6373':'osa','mdt693b':'mdt'}.get(d.family)
            if family: self._add_family(family,d.name)
        self.log.appendPlainText('Discovery complete: supported devices added.')

    def _add(self, name):
        if not name or self._closing: return
        if name in self.dynamic_windfreak_tabs:
            self.windfreak_subtabs.setCurrentWidget(self.dynamic_windfreak_tabs[name]); return
        panel = WindfreakTab(name,*self._endpoint(),self,channel_names=self.cfg.get('windfreak_channel_names',{}).get(name,{}))
        panel.endpoint_provider = self._endpoint
        panel.log_message.connect(self.log.appendPlainText)
        panel.channel_names_changed.connect(lambda names,n=name:self.cfg.setdefault('windfreak_channel_names',{}).__setitem__(n,names))
        self.dynamic_windfreak_tabs[name] = panel
        self.windfreak_subtabs.addTab(panel,name)
        self.windfreak_subtabs.setCurrentWidget(panel)

    def _add_family(self, family, name):
        if family=='windfreak':return self._add(name)
        if not name or self._closing:return
        panels=self.family_tabs[family]; tabs=self.family_subtabs[family]
        if family=='motors':
            if name not in panels:
                panels[name]=self.motor_tab.add_motor(name)
                panels[name].log_message.connect(self.log.appendPlainText)
            self.others_tabs.setCurrentWidget(self.motor_tab)
            return
        if name in panels:
            tabs.setCurrentWidget(panels[name]);return
        if family in ('ds1052e','mso7054'):
            panel={'ds1052e':DS1052ETab,'mso7054':MSO7054Tab}[family](name,*self._endpoint(),self)
        elif family in ('thermotek','keithley'):panel=EquipmentTab(family,name,*self._endpoint(),self)
        elif family in ('osa','mdt','fpga','motors'):panel=AuxiliaryTab(family,name,*self._endpoint(),self)
        else:panel=RFDeviceTab(family,name,*self._endpoint(),self)
        if family in ("mdt","fpga"):panel.attach_automation(self._bindings)
        panel.endpoint_provider=self._endpoint
        panel.log_message.connect(self.log.appendPlainText)
        panels[name]=panel;tabs.addTab(panel,name)

    def _panels(self):
        return [panel for panels in self.family_tabs.values() for panel in panels.values()] + [self.ccd_tab] + self.ccd_tab.oven_panel.lifecycle_panels()

    def _bindings(self):
        bindings = {family+':'+name:(family,p.worker.operation_bridge)
                for family,panels in self.family_tabs.items() for name,p in panels.items() if p.connected}
        if self.ccd_tab.connected:
            bindings['ccd:ccd_local'] = ('ccd', self.ccd_tab.worker.operation_bridge)
        return bindings

    def closeEvent(self, event):
        if not self._closing:
            if not self.workflow_tab.confirm_close():
                event.ignore()
                return
            self._closing = True
            self.workflow_tab.shutdown()
            self.discovery_worker.shutdown()
            self.centralWidget().setEnabled(False)
            for p in self._panels():p.worker.cancel_backgrounds()
            self._shutdown_workers_when_ready()
            self.cfg.update(server_host=self._endpoint()[0],server_port=self._endpoint()[1],windfreak_names=list(self.dynamic_windfreak_tabs))
            for family,panels in self.family_tabs.items(): self.cfg[family+'_names']=list(panels)
            self.cfg['ccd_options'] = self.ccd_tab.settings()
            save_settings(self.cfg)
            self.close_timer.start(100)
        if self._running(): event.ignore()
        else: event.accept()

    def _running(self):
        return self.workflow_tab.still_running() or self.discovery_worker.isRunning() or any(p.still_running() for p in self._panels())

    def _shutdown_workers_when_ready(self):
        if self._workers_shutdown:return
        from labremote.runtime.workflow_runner import _TASK_LOCK
        with _TASK_LOCK:tasks={task for panel in self._panels() for task in panel.worker._background_tasks}
        if any(task.running() for task in tasks):return
        self._workers_shutdown=True
        for panel in self._panels():panel.shutdown()

    def _close_ready(self):
        self._shutdown_workers_when_ready()
        if not self._running():
            self.close_timer.stop(); self.close()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host'); parser.add_argument('--port',type=int)
    args=parser.parse_args()
    cfg=load_settings()
    if args.host: cfg['server_host']=args.host
    if args.port: cfg['server_port']=args.port
    app=QtWidgets.QApplication(sys.argv)
    apply_theme(app)
    window=Window(cfg); window.show()
    sys.exit(app.exec_())
