"""Manual controls for OSA/MDT/local FPGA/QCoDeS motors, all through common APIs."""
from collections import deque
import time
from PyQt5 import QtCore, QtWidgets
from labremote.api.devices import device_api
from labremote.config.device_config import load_device_config
from labremote.runtime.parameters import LIBRARY


class AuxiliaryTab(QtWidgets.QWidget):
    log_message=QtCore.pyqtSignal(str)

    def __init__(self,family,name,host,port,parent=None):
        super().__init__(parent)
        from labremote.devices.osa.worker import OSAWorker
        from labremote.devices.mdt.worker import MDTWorker
        from labremote.devices.fpga.worker import FPGAWorker
        from labremote.devices.motors.worker import MotorWorker
        self.family,self.name,self.endpoint=family,name,(host,port)
        self.connected=False;self._closing=False;self.labels={};self.editors={};self.buttons=[]
        self.samples=deque(maxlen=1000);self.config=load_device_config(family,name)
        self.worker={'osa':OSAWorker,'mdt':MDTWorker,'fpga':FPGAWorker,'motors':MotorWorker}[family]()
        self.api=device_api(self.worker)
        root=QtWidgets.QVBoxLayout(self)
        if family=='fpga':
            line=QtWidgets.QHBoxLayout();root.addLayout(line)
            self.serial=QtWidgets.QLineEdit(self.config['connection']['serial_port']);self.serial.setPlaceholderText('COM port, e.g. COM5')
            from labremote.devices.fpga.ports import PortScanner, load_port
            self._serial_ports = []; self._saved_port = {}; self._port_error = ''
            try: self._saved_port = load_port(name)
            except Exception as exc: self._port_error = str(exc)
            if self._saved_port.get('device'): self.serial.setText(self._saved_port['device'])
            line.addWidget(QtWidgets.QLabel('Local FPGA serial port'));line.addWidget(self.serial)
            self.port_choices=QtWidgets.QComboBox();line.addWidget(self.port_choices,1)
            self.scan_ports=QtWidgets.QPushButton('포트 검색');line.addWidget(self.scan_ports)
            self.port_scanner=PortScanner(self)
            self.port_scanner.found.connect(self._ports_found)
            self.port_scanner.failed.connect(self._ports_failed)
            self.port_scanner.finished.connect(lambda:self.scan_ports.setEnabled(not self.connected and not self._closing))
            self.scan_ports.clicked.connect(self._search_ports)
            self.port_choices.activated.connect(lambda _:self.serial.setText(self.port_choices.currentData() or self.serial.text()))
        elif family=='motors':
            form=QtWidgets.QFormLayout();root.addLayout(form);cfg=self.config['connection']
            self.host=QtWidgets.QLineEdit(cfg['host']);self.port=QtWidgets.QSpinBox();self.port.setRange(1,65535);self.port.setValue(cfg['port'])
            self.target=QtWidgets.QLineEdit(self.config.get('instrument',name))
            for title,editor in [('Instrument Server',self.host),('Port',self.port),('Instrument',self.target)]:form.addRow(title,editor)
        row=QtWidgets.QHBoxLayout();root.addLayout(row)
        self.connect_btn=QtWidgets.QPushButton('Connect');self.disconnect_btn=QtWidgets.QPushButton('Disconnect')
        row.addWidget(self.connect_btn);row.addWidget(self.disconnect_btn)
        self.connect_btn.clicked.connect(self._connect);self.disconnect_btn.clicked.connect(self.api.disconnect)
        self._button(row,'Read all',self.api.refresh);self._button(row,'Cancel operation / workflow',self.api.cancel)
        self.status=QtWidgets.QLabel(name+' — Disconnected');root.addWidget(self.status)
        self.message=QtWidgets.QLabel();self.message.setWordWrap(True);root.addWidget(self.message)
        grid=QtWidgets.QGridLayout();root.addLayout(grid)
        if family=='osa':
            low=self._number(grid,'frequency_start_thz','Start (THz)',10,856.5,6,370)
            high=self._number(grid,'frequency_stop_thz','Stop (THz)',10,856.5,6,380)
            self._button(grid,'Apply range',lambda:self.api.set_range(low.value(),high.value()))
            ref=self._number(grid,'reference_level_dbm','Reference (dBm)',-100,30,2,-30)
            div=self._number(grid,'db_per_div','dB / div',.1,20,2,10)
            self._button(grid,'Apply level',lambda:self.api.set_level(ref.value(),div.value()))
            row=QtWidgets.QHBoxLayout();root.addLayout(row)
            self.trace=QtWidgets.QComboBox();self.trace.addItems(['TRA','TRB','TRC','TRD','TRE','TRF','TRG']);row.addWidget(self.trace)
            self._button(row,'Apply trace',lambda:self.api.set_trace(self.trace.currentText()))
            self._button(row,'Auto reference ON',lambda:self.api.set_auto_reference(True))
            self._button(row,'Auto reference OFF',lambda:self.api.set_auto_reference(False))
            self._button(row,'Zero',self.api.zero);self._button(row,'Abort',self.api.abort)
            self._label(grid,'auto_reference','Auto reference');self._label(grid,'trace_name','Trace')
            self._repeat_controls(root,self.api.read_spectrum,lambda:self.api.start_spectrum(interval_s=self.interval.value()),self.api.stop_spectrum)
            self._plot(root)
            row=QtWidgets.QHBoxLayout();root.addLayout(row)
            self.spectrum_auto_y=QtWidgets.QCheckBox('Auto Y min/max');row.addWidget(self.spectrum_auto_y)
            self.spectrum_y_min=QtWidgets.QDoubleSpinBox();self.spectrum_y_max=QtWidgets.QDoubleSpinBox()
            for field,value,label in ((self.spectrum_y_min,-100,'Y min (dBm)'),(self.spectrum_y_max,0,'Y max (dBm)')):
                field.setRange(-300,100);field.setDecimals(2);field.setValue(value)
                row.addWidget(QtWidgets.QLabel(label));row.addWidget(field)
            self.spectrum_limit_error=QtWidgets.QLabel();root.addWidget(self.spectrum_limit_error)
            self.spectrum_auto_y.toggled.connect(self._spectrum_limits)
            self.spectrum_axis=None
            for field in (self.spectrum_y_min,self.spectrum_y_max):field.valueChanged.connect(self._spectrum_limits)
            self._spectrum_limits()
        elif family=='mdt':
            limits=self.config['limits']
            for axis in 'XYZ':
                editor=self._number(grid,axis.lower()+'.voltage',axis+' (V)',limits['min_voltage'],limits['max_voltage'],3,0)
                self._button(grid,'Apply '+axis,lambda a=axis,e=editor:self.api.set_voltage(a,e.value()))
            for path,title in [('output_limit_v','Hardware limit (V)'),('software_minimum','Server minimum (V)'),('software_maximum','Server maximum (V)'),('master_scan_enabled','Master scan')]:self._label(grid,path,title)
            self._button(grid,'Master scan ON',lambda:self.api.set_master_scan(True))
            self._button(grid,'Master scan OFF',lambda:self.api.set_master_scan(False))
        elif family=='fpga':
            from labremote.devices.fpga.controller import OUTPUTS
            self.output_buttons={};self.output_pending={}
            for index,name in enumerate(OUTPUTS):
                button=QtWidgets.QPushButton(name+'\nUnknown');button.setMinimumHeight(48)
                button.clicked.connect(lambda _,n=name:self._toggle_output(n))
                grid.addWidget(button,index//4,index%4);self.output_buttons[name]=button;self.buttons.append(button)
            from labremote.ui.fpga_count_tab import FPGACountTab
            self.input_tab=FPGACountTab(self.worker,self);self.input_tab.hide()
        else:
            limits=self.config['limits'];editor=self._number(grid,'position','Position (server units)',limits['min_position'],limits['max_position'],6,limits['min_position'])
            self._label(grid,'status','Server status')
            row=QtWidgets.QHBoxLayout();root.addLayout(row)
            for text,action in [('Open',self.api.open),('Move',lambda:self.api.move(editor.value())),('Home',self.api.home),('Stop (queued)',self.api.stop),('Close',self.api.close)]:self._button(row,text,action)
            root.addWidget(QtWidgets.QLabel('Each motor has its own FIFO. Cancel waits for an in-flight command to return; it does not undo motion.'))
        root.addStretch()
        self.worker.connected.connect(self._connected);self.worker.disconnected.connect(self._disconnected)
        self.worker.snapshot.connect(self._snapshot);self.worker.failure.connect(self._failure)
        self.worker.handle_changed.connect(self._result)
        if hasattr(self.worker,'waveform_changed'):self.worker.waveform_changed.connect(self._repeat_changed)
        self.timer=QtCore.QTimer(self);self.timer.setInterval(60000)
        self.timer.timeout.connect(lambda:self.api.auto_monitor() if self.connected else None);self.timer.start()
        self.worker.start();self._buttons()
        if self.family=='fpga':
            self.message.setText(self._port_error)
            self._search_ports()

    def attach_automation(self,bindings):
        if self.family not in ('mdt','fpga'):return
        manual=QtWidgets.QWidget();manual.setLayout(self.layout())
        root=QtWidgets.QVBoxLayout(self);self.automation_tabs=QtWidgets.QTabWidget();root.addWidget(self.automation_tabs)
        self.automation_tabs.addTab(manual,'Manual')
        if self.family=='mdt':
            from labremote.ui.pid_tab import PIDTab
            self.pid_tab=PIDTab(self.worker,bindings,self)
            self.automation_tabs.addTab(self.pid_tab,'OSA PID')
        else:
            from labremote.ui.motor_scan_tab import MotorScanTab
            self.automation_tabs.addTab(self.input_tab,'Input counts')
            self.scan_tabs=[MotorScanTab(self.worker,bindings,n,self) for n in range(1,5)]
            for panel in self.scan_tabs:self.automation_tabs.addTab(panel,panel.title)

    def _button(self,layout,text,callback):
        button=QtWidgets.QPushButton(text);button.clicked.connect(lambda _:callback());self.buttons.append(button)
        if isinstance(layout,QtWidgets.QGridLayout):layout.addWidget(button,layout.rowCount(),2)
        else:layout.addWidget(button)
        return button

    def _label(self,grid,path,title):
        row=grid.rowCount();label=QtWidgets.QLabel('Unknown');label.setWordWrap(True)
        grid.addWidget(QtWidgets.QLabel(title),row,0);grid.addWidget(label,row,1);self.labels[path]=label
        return row

    def _number(self,grid,path,title,minimum,maximum,decimals,value):
        row=self._label(grid,path,title);editor=QtWidgets.QDoubleSpinBox();editor.setDecimals(decimals)
        editor.setRange(minimum,maximum);editor.setValue(value);grid.addWidget(editor,row,2);self.editors[path]=editor
        return editor

    def _repeat_controls(self,root,once,start,stop):
        row=QtWidgets.QHBoxLayout();root.addLayout(row)
        self._button(row,'Read once',once);self._button(row,'Start repeat',start);self._button(row,'Stop repeat',stop)
        self.interval=QtWidgets.QDoubleSpinBox();self.interval.setRange(.1,3600);self.interval.setValue(self.config['acquisition']['interval_s'])
        row.addWidget(self.interval);row.addWidget(QtWidgets.QLabel('seconds after each acquisition'))
        self.repeat_status=QtWidgets.QLabel('Repeat stopped');root.addWidget(self.repeat_status)

    def _plot(self,root):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        self.figure=Figure(figsize=(9,3));self.canvas=FigureCanvasQTAgg(self.figure);self.canvas.setMinimumHeight(240);root.addWidget(self.canvas)

    def _search_ports(self):
        if self.connected or self._closing or self.port_scanner.isRunning():return
        self.scan_ports.setEnabled(False);self.port_scanner.start()

    def _ports_failed(self,message):
        if not self._closing:self.message.setText('포트 검색 실패: '+message)

    def _ports_found(self,ports):
        if self._closing:return
        from labremote.devices.fpga.ports import remembered_device
        self._serial_ports=ports;self.port_choices.clear()
        for p in ports:self.port_choices.addItem(p['device']+' · '+str(p['description'])+' · '+str(p['serial_number'] or 'USB serial 없음'),p['device'])
        old=self.serial.text().strip()
        remembered=remembered_device(self._saved_port,ports)
        if not self.connected and (not old or old==self._saved_port.get('device')) and remembered:self.serial.setText(remembered)
        index=self.port_choices.findData(self.serial.text().strip());self.port_choices.setCurrentIndex(index)
        self.message.setText(f'{len(ports)}개 포트 검색됨. 목록에서 사용할 FPGA 포트를 선택하세요.'+(' 기억한 포트가 현재 목록에 없습니다.' if remembered and self.port_choices.findData(remembered)<0 else ''))

    def _connect(self):
        if self.family=='fpga':return self.api.connect_serial(self.serial.text().strip(),self.name)
        if self.family=='motors':return self.api.connect_motor(self.host.text().strip(),self.port.value(),self.target.text().strip())
        endpoint=self.endpoint_provider() if hasattr(self,'endpoint_provider') else self.endpoint
        return self.api.connect(*endpoint,self.name)

    def _connected(self,info):
        if self.family=='fpga':
            from labremote.devices.fpga.ports import save_port, load_port
            try:
                save_port(self.name,info['port'],self._serial_ports);self._saved_port=load_port(self.name)
                self.serial.setText(info['port'])
            except Exception as exc:self.log_message.emit('FPGA port memory: '+str(exc))
        self.connected=True;self.status.setText(self.name+' — Connected');self._buttons();self.api.refresh()

    def _disconnected(self,message):
        self.connected=False;self.status.setText(message);self._snapshot();self._buttons()

    def _snapshot(self,*args):
        for path,label in self.labels.items():
            state=LIBRARY.read((self.worker._execution_device,path))
            valid=self.connected and state.quality=='valid' and state.verification not in ('pending','failed','mismatch')
            value=state.observed if valid else None
            if self.family=='motors' and path=='status' and isinstance(value,dict):
                position_state=LIBRARY.read((self.worker._execution_device,'position'))
                if state.observed_at>=max(position_state.observed_at,position_state.attempted_at):
                    position=value.get('position');self.labels['position'].setText(str(position) if position is not None else 'Unknown')
            label.setText('Unknown' if value is None else str(value));label.setToolTip(state.error or '')
        if hasattr(self,'output_buttons'):
            state=LIBRARY.read((self.worker._execution_device,'states'))
            from labremote.devices.fpga.controller import OUTPUTS
            state_time=max(state.attempted_at,state.observed_at)
            for name,label in self.output_buttons.items():
                individual=LIBRARY.read((self.worker._execution_device,'outputs.'+name))
                individual_time=max(individual.attempted_at,individual.observed_at)
                latest=individual if individual_time>state_time else state
                value=None;commanded=False
                pending=name in self.output_pending.values() or latest.verification=='pending'
                failed=latest.error is not None or latest.verification in ('failed','mismatch')
                if latest.quality=='valid' and not failed and not pending:
                    value=individual.observed if latest is individual else (state.observed or {}).get(name)
                # Slow-port commands have no physical readback. Use only a
                # successful library assignment, never UI-local command history.
                if (value is None and OUTPUTS[name][1]!=0 and not failed and not pending
                        and individual.verification=='unverified' and individual.error is None
                        and (latest is individual or latest.quality=='valid')):
                    value=individual.requested;commanded=isinstance(value,bool)
                if not self.connected or pending:value=None
                text='Pending' if pending else 'Unknown' if value is None else 'ON' if value else 'OFF'
                if self.connected and value is None and not pending and not failed and OUTPUTS[name][1]!=0:text='읽기 미지원'
                label.setText(name+'\n'+text+(' *' if commanded and value is not None else ''))
                label.setProperty('outputValue',value)
                color='#238636' if value is True else '#b42318' if value is False else '#616161'
                label.setStyleSheet('QPushButton { background-color: '+color+'; color: white; border-radius: 4px; padding: 6px; }')
                label.setToolTip('Commanded state only; this output has no physical readback.' if commanded else 'Click to turn OFF' if value else 'Click to turn ON')
                if self.connected and value is None and not pending and not failed and OUTPUTS[name][1]!=0:
                    label.setToolTip('Slow port: 상태 읽기 미지원. 클릭하면 ON 명령을 보냅니다. ON/OFF *는 실제 읽기값이 아닌 마지막 성공 명령입니다.')
                label.setEnabled(self.connected and not pending)

    def _toggle_output(self,name):
        value=not bool(self.output_buttons[name].property('outputValue'))
        handle=self.api.set_output(name,value)
        self.output_pending[handle.request_id]=name
        self._snapshot()

    def _result(self,handle):
        if self.family=='fpga' and handle.done.is_set():
            self.output_pending.pop(handle.request_id,None)
        self._buttons()
        if not handle.done.is_set() or self._closing:return
        self._snapshot()
        if handle.error is not None:return
        self.message.setText(handle.action+' completed')
        if handle.action=='SET_OUTPUT':self.api.refresh()
        if self.family=='fpga' or handle.action not in ('SPECTRUM','MEASURE'):return
        if getattr(self,'_last_result',None)==handle.request_id:return
        self._last_result=handle.request_id
        value=handle.result;self.figure.clear();axis=self.figure.add_subplot(111)
        if handle.action=='SPECTRUM':
            axis.plot(value['frequency_thz'],value['power_dbm']);axis.set_xlabel('Frequency (THz)');axis.set_ylabel('Power (dBm)')
            self.spectrum_axis=axis;self._spectrum_limits()
        else:
            self.samples.append((time.monotonic(),value['count']));self.count.setText(f"Count: {value['count']} / {value['ms']} ms")
            axis.plot([t-self.samples[0][0] for t,c in self.samples],[c for t,c in self.samples]);axis.set_xlabel('Elapsed seconds');axis.set_ylabel('Counts')
        axis.grid(True,alpha=.3);self.figure.subplots_adjust(left=.12,right=.87,bottom=.2,top=.94);self.canvas.draw_idle()

    def _spectrum_limits(self,*args):
        automatic=self.spectrum_auto_y.isChecked()
        for field in (self.spectrum_y_min,self.spectrum_y_max):field.setEnabled(not automatic)
        low,high=self.spectrum_y_min.value(),self.spectrum_y_max.value()
        self.spectrum_limit_error.setText('Y min must be less than Y max' if not automatic and low>=high else '')
        if not automatic and low<high:self._spectrum_fixed_limits=(low,high)
        axis=self.spectrum_axis
        if axis is None:return
        axis.set_autoscaley_on(automatic)
        if automatic:axis.relim();axis.autoscale_view(scalex=False,scaley=True)
        else:axis.set_ylim(*self._spectrum_fixed_limits)
        self.canvas.draw_idle()

    def _repeat_changed(self,handle):
        if hasattr(self,'repeat_status'):self.repeat_status.setText('Repeat: '+handle.status)

    def _failure(self,action,message):
        self.message.setText(action+': '+message);self.log_message.emit(self.name+': '+message)
        if self._closing:return
        box=QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning,self.name+' — '+action,message,parent=self)
        box.setAttribute(QtCore.Qt.WA_DeleteOnClose);box.open()

    def _buttons(self):
        from labremote.ui.connection_status import connection_color
        connection_color(self.connect_btn,'connected' if self.connected and not self.worker.connection_error and not getattr(self.worker,'io_fault',False) else 'disconnected')
        if self.family=='fpga':
            self.scan_ports.setEnabled(not self.connected and not self.port_scanner.isRunning())
            self.port_choices.setEnabled(not self.connected)
        self.connect_btn.setEnabled(not self.connected and not self.worker.has_requests());self.disconnect_btn.setEnabled(self.connected)
        for button in self.buttons:button.setEnabled(self.connected)
        if self.family=='fpga':self._snapshot()
        for name in ('serial','host','port','target'):
            widget=getattr(self,name,None)
            if widget is not None:widget.setEnabled(not self.connected)

    def shutdown(self):
        if hasattr(self,'daily_tab'):self.daily_tab.shutdown()
        self._closing=True;self.timer.stop();self.worker.shutdown()
    def still_running(self):return (hasattr(self,'daily_tab') and self.daily_tab.still_running()) or (hasattr(self,'port_scanner') and self.port_scanner.isRunning()) or self.worker.isRunning() or (hasattr(self.worker,'waveform_runner') and self.worker.waveform_runner.running())
