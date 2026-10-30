"""THERMOTEK and Keithley controls over the common device API and library."""
from collections import deque
import time
from PyQt5 import QtCore, QtWidgets
from labremote.api.devices import device_api
from labremote.runtime.parameters import LIBRARY, registry
from labremote.config.device_config import load_device_config


class EquipmentTab(QtWidgets.QWidget):
    log_message=QtCore.pyqtSignal(str)

    def __init__(self,family,name,host,port,parent=None):
        super().__init__(parent)
        from labremote.devices.thermotek.worker import ThermotekWorker
        from labremote.devices.keithley.worker import KeithleyWorker
        self.family,self.name,self.endpoint=family,name,(host,port)
        self.connected=False;self._shutting_down=False
        self.rows={};self.inputs=[];self.labels={};self.samples=deque(maxlen=1000)
        self.worker=(ThermotekWorker if family=='thermotek' else KeithleyWorker)()
        self.api=device_api(self.worker)
        root=QtWidgets.QVBoxLayout(self)
        line=QtWidgets.QHBoxLayout();root.addLayout(line)
        self.connect_btn=QtWidgets.QPushButton('Connect');self.disconnect_btn=QtWidgets.QPushButton('Disconnect')
        self.read_btn=QtWidgets.QPushButton('Read once');self.cancel_btn=QtWidgets.QPushButton('Cancel operation / workflow')
        for button in (self.connect_btn,self.disconnect_btn,self.read_btn,self.cancel_btn):line.addWidget(button)
        self.status=QtWidgets.QLabel(name+' — Disconnected');root.addWidget(self.status)
        self.message=QtWidgets.QLabel();self.message.setWordWrap(True);root.addWidget(self.message)
        self.connect_btn.clicked.connect(self._connect)
        self.disconnect_btn.clicked.connect(self.api.disconnect)
        self.cancel_btn.clicked.connect(self.api.cancel)
        self.read_btn.clicked.connect(self.api.read_telemetry if family=='thermotek' else self.api.refresh)
        if family=='thermotek':
            box=QtWidgets.QGroupBox('ThermoTek T257P');grid=QtWidgets.QGridLayout(box);root.addWidget(box)
            self._number(grid,'temperature_setpoint','Target temperature',5,40,'°C',self.api.set_target)
            for path,title in [('supply_temperature','Supply °C'),('ambient_temperature','Ambient °C'),('watchdog_json','Pump / controller / alarms')]:
                label=QtWidgets.QLabel('Unknown');label.setWordWrap(True);self.labels[path]=label
                n=grid.rowCount();grid.addWidget(QtWidgets.QLabel(title),n,0);grid.addWidget(label,n,1,1,4)
            line=QtWidgets.QHBoxLayout();root.addLayout(line)
            self.run_btn=QtWidgets.QPushButton('Pump RUN');self.stop_btn=QtWidgets.QPushButton('Pump STOP')
            self.run_btn.clicked.connect(self.api.start);self.stop_btn.clicked.connect(self.api.stop)
            line.addWidget(self.run_btn);line.addWidget(self.stop_btn);self.inputs.extend([self.run_btn,self.stop_btn])
            self.live_btn=QtWidgets.QPushButton('Start monitoring');self.live_btn.clicked.connect(self._toggle_monitor)
            self.interval=QtWidgets.QDoubleSpinBox();self.interval.setRange(3,3600)
            self.interval.setValue(load_device_config(family,name)['acquisition']['interval_s'])
            line.addWidget(self.live_btn);line.addWidget(self.interval);line.addWidget(QtWidgets.QLabel('seconds after each acquisition'))
            self.repeat_status=QtWidgets.QLabel('Monitoring stopped');root.addWidget(self.repeat_status)
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
            self.figure=Figure(figsize=(9,4));self.canvas=FigureCanvasQTAgg(self.figure);root.addWidget(self.canvas)
            self.worker.waveform_changed.connect(self._repeat_changed)
            self.worker.handle_changed.connect(self._telemetry)
            diagnostic=QtWidgets.QHBoxLayout();root.addLayout(diagnostic)
            self.diagnostic=QtWidgets.QComboBox()
            self.diagnostic.addItems(['warning_register_raw','alarm_l2_1_raw','alarm_l2_2_raw','control_sensor_raw',
                'return_temperature_raw','external_rtd_temperature_raw','external_thermistor_temperature_raw',
                'tec1_current_raw','tec2_current_raw','tec_drive_raw','pwm_raw','pid_status_raw','uptime_raw',
                'high_supply_alarm_c_raw','low_supply_alarm_c_raw','high_ambient_alarm_c_raw','low_ambient_alarm_c_raw',
                'low_flow_warning_lpm_raw','low_flow_alarm_lpm_raw','fan1_speed_hz_raw','fan2_speed_hz_raw','fan3_speed_hz_raw','fan4_speed_hz_raw'])
            read_diagnostic=QtWidgets.QPushButton('Read diagnostic (raw protocol units)')
            read_diagnostic.clicked.connect(lambda:self.api.acquire(self.diagnostic.currentText()))
            self.inputs.append(read_diagnostic);diagnostic.addWidget(self.diagnostic);diagnostic.addWidget(read_diagnostic)
            self.diagnostic_value=QtWidgets.QLabel('Not read');root.addWidget(self.diagnostic_value)
        else:
            config=load_device_config(family,name)
            self.k_rows={}
            load=QtWidgets.QPushButton('현재값 가져오기');load.clicked.connect(self._load_inputs)
            root.addWidget(load);self.inputs.append(load)
            advanced_toggle=QtWidgets.QCheckBox('OVP 상세 설정 표시')
            root.addWidget(advanced_toggle)
            for channel in (1,2,3):
                api=device_api(self.worker,channel=channel);prefix=f'ch{channel}.'
                limits=config['channels'][f'CH{channel}']['limits']
                vmax=min(30 if channel<3 else 5,limits['max_voltage_v']);imax=min(3,limits['max_current_a'])
                box=QtWidgets.QGroupBox(f'CH{channel} | 0–{vmax:g} V · 0–{imax:g} A')
                grid=QtWidgets.QGridLayout(box);root.addWidget(box)
                v=QtWidgets.QDoubleSpinBox();v.setDecimals(6);v.setRange(0,vmax)
                i=QtWidgets.QDoubleSpinBox();i.setDecimals(6);i.setRange(0,imax)
                vb=QtWidgets.QPushButton('Set V');ib=QtWidgets.QPushButton('Set I')
                vb.clicked.connect(lambda _,m=api.set_voltage,e=v:m(e.value()))
                ib.clicked.connect(lambda _,m=api.set_current,e=i:m(e.value()))
                for col,widget in enumerate((QtWidgets.QLabel('Target voltage (V)'),v,vb,QtWidgets.QLabel('Current limit (A)'),i,ib)):
                    grid.addWidget(widget,0,col)
                self.rows[prefix+'target_voltage']=v;self.rows[prefix+'target_current']=i
                measure=QtWidgets.QLabel('Measured: Unknown');target=QtWidgets.QLabel('Setpoint readback: Unknown')
                output=QtWidgets.QLabel('Unknown');off=QtWidgets.QPushButton('Output OFF');on=QtWidgets.QPushButton('Output ON')
                off.clicked.connect(api.off);on.clicked.connect(api.on)
                grid.addWidget(measure,1,0,1,3);grid.addWidget(output,1,3);grid.addWidget(off,1,4);grid.addWidget(on,1,5)
                grid.addWidget(target,2,0,1,6);grid.setColumnStretch(1,1);grid.setColumnStretch(4,1)
                self.inputs.extend((vb,ib,off,on));self.labels[prefix+'output']=output
                self.k_rows[channel]=dict(measure=measure,target=target,output=output,on=on,grid=grid)
                advanced=QtWidgets.QWidget();ag=QtWidgets.QGridLayout(advanced);grid.addWidget(advanced,3,0,1,6)
                self._number(ag,prefix+'voltage_limit','OVP limit',0,vmax,'V',api.set_voltage_limit)
                ovp=QtWidgets.QLabel('Unknown');self.labels[prefix+'voltage_limit_state']=ovp
                enable=QtWidgets.QPushButton('Enable OVP');disable=QtWidgets.QPushButton('Disable OVP')
                enable.clicked.connect(lambda _,a=api:a.set_voltage_limit_enabled(True))
                disable.clicked.connect(lambda _,a=api:a.set_voltage_limit_enabled(False))
                ag.addWidget(ovp,2,1);ag.addWidget(enable,2,2);ag.addWidget(disable,2,4)
                self.inputs.extend((enable,disable));advanced.hide();advanced_toggle.toggled.connect(advanced.setVisible)
            off=QtWidgets.QPushButton('All outputs OFF');off.clicked.connect(self.api.all_off)
            root.addWidget(off);self.inputs.append(off)
            root.addWidget(QtWidgets.QLabel('Limits: labremote/config/keithley/device_config.yml · Monitoring every 60 s'))
        root.addStretch()
        self.worker.connected.connect(self._connected);self.worker.disconnected.connect(self._disconnected)
        self.worker.snapshot.connect(self._snapshot);self.worker.failure.connect(self._failure)
        self.worker.handle_changed.connect(lambda _:self._buttons())
        self.worker.completed.connect(lambda action:self.message.setText(action+' completed'))
        self.timer=QtCore.QTimer(self);self.timer.setInterval(60000)
        self.timer.timeout.connect(lambda:self.api.monitor() if self.connected and self.family=='keithley' else None)
        self.timer.start();self.worker.start();self._buttons()

    def _number(self,grid,path,title,low,high,unit,method):
        n=grid.rowCount();editor=QtWidgets.QDoubleSpinBox();editor.setDecimals(3);editor.setRange(low,high)
        label=QtWidgets.QLabel('Unknown');apply=QtWidgets.QPushButton('Apply');read=QtWidgets.QPushButton('Read')
        for i,w in enumerate((QtWidgets.QLabel(title),label,editor,QtWidgets.QLabel(unit),apply,read)):grid.addWidget(w,n,i)
        apply.clicked.connect(lambda:method(editor.value()));read.clicked.connect(lambda:self.api.acquire(path))
        self.labels[path]=label;self.rows[path]=editor;self.inputs.extend([apply,read])

    def _connect(self):
        endpoint=self.endpoint_provider() if hasattr(self,'endpoint_provider') else self.endpoint
        return self.api.connect(*endpoint,self.name)

    def _connected(self,info):
        self.connected=True;self.status.setText(self.name+' — Connected');self._buttons()
        if self.family=='keithley':self._load_inputs()

    def _load_inputs(self):
        self._fill_inputs=True
        return self.api.refresh()

    def _disconnected(self,message):
        self.connected=False;self.status.setText(message);self._snapshot({},'DISCONNECT');self._buttons()

    def _snapshot(self,data,action):
        for path,label in self.labels.items():
            state=LIBRARY.read((self.worker._execution_device,path))
            valid=self.connected and state.quality=='valid' and state.verification not in ('failed','mismatch','pending')
            value=state.observed if valid else None
            if isinstance(value,dict):text='; '.join(f'{key}: {v}' for key,v in value.items())
            elif isinstance(value,bool):text='ON' if value else 'OFF'
            else:text='Unknown' if value is None else str(value)
            label.setText(text);label.setToolTip(state.error or '')
        if self.family=='keithley':
            def number(path,unit):
                state=LIBRARY.read((self.worker._execution_device,path))
                valid=self.connected and state.quality=='valid' and state.verification not in ('failed','mismatch','pending')
                return f'{state.observed:.6g} {unit}' if valid and state.observed is not None else '— '+unit
            for ch,row in self.k_rows.items():
                prefix=f'ch{ch}.'
                row['measure'].setText('Measured: '+number(prefix+'voltage','V')+' | '+number(prefix+'current','A')+' | '+number(prefix+'power','W'))
                row['target'].setText('Setpoint readback: '+number(prefix+'target_voltage','V')+' | '+number(prefix+'target_current','A'))
                from labremote.ui.theme import RF_INACTIVE_STYLE
                on=row['output'].text()=='ON'
                row['on'].setStyleSheet('QPushButton {background-color:#20554f;color:#9ef1df;}' if on else RF_INACTIVE_STYLE)
            if action=='REFRESH' and getattr(self,'_fill_inputs',False):
                for path,editor in self.rows.items():
                    state=LIBRARY.read((self.worker._execution_device,path))
                    if state.quality=='valid' and state.observed is not None and editor.minimum()<=state.observed<=editor.maximum():
                        editor.setValue(state.observed)
                self._fill_inputs=False
        if hasattr(self,'diagnostic'):
            state=LIBRARY.read((self.worker._execution_device,self.diagnostic.currentText()))
            self.diagnostic_value.setText(str(state.observed) if self.connected and state.quality=='valid' else 'Unknown')

    def _toggle_monitor(self):
        if self.worker.waveform_runner.running():self.api.stop_monitoring()
        else:self.api.start_monitoring(interval_s=self.interval.value())

    def _repeat_changed(self,handle):
        self.repeat_status.setText('Monitoring: '+handle.status)
        self.live_btn.setText('Start monitoring' if handle.done.is_set() else 'Stop monitoring')
        self._buttons()

    def _telemetry(self,handle):
        if handle.action!='TELEMETRY' or not handle.done.is_set() or handle.error is not None or self._shutting_down:return
        if any(sample[0]==handle.request_id for sample in self.samples):return
        self.samples.append((handle.request_id,time.monotonic(),handle.result))
        self._plot_temperatures()

    def _plot_temperatures(self):
        self.figure.clear();main=self.figure.add_subplot(111)
        self.temperature_axes={};lines=[]
        times=[s[1]-self.samples[0][1] for s in self.samples]
        series=[('supply_temperature','Supply','#76baff'),('ambient_temperature','Ambient','#f3c46b'),('temperature_setpoint','Target','#79df96')]
        # Each axis has its own center, but all three show the same temperature span.
        span=max([1.0]+[(max(s[2][key] for s in self.samples)-min(s[2][key] for s in self.samples))*1.2 for key,_,_ in series])
        for index,(key,title,color) in enumerate(series):
            axis=main if index==0 else main.twinx()
            if index==2:axis.spines['right'].set_position(('axes',1.14))
            values=[s[2][key] for s in self.samples];center=(min(values)+max(values))/2
            axis.set_ylim(center-span/2,center+span/2);axis.set_ylabel(title+' (°C)',color=color)
            axis.tick_params(axis='y',colors=color)
            line,=axis.plot(times,values,color=color,label=title,linestyle='--' if index==2 else '-',marker='.' if len(values)==1 else None)
            lines.append(line);self.temperature_axes[key]=axis
        main.set_xlabel('Elapsed seconds');main.grid(True,alpha=.25);main.legend(lines,[line.get_label() for line in lines],loc='upper left')
        self.figure.subplots_adjust(left=.1,right=.77,bottom=.16,top=.94);self.canvas.draw_idle()

    def _failure(self,action,message):
        self.message.setText(action+': '+message);self.log_message.emit(self.name+': '+message)
        if self._shutting_down:return
        box=QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning,self.name+' — '+action,message,parent=self)
        box.setAttribute(QtCore.Qt.WA_DeleteOnClose);box.open()

    def _buttons(self):
        self.connect_btn.setEnabled(not self.connected and not self.worker.has_requests())
        self.disconnect_btn.setEnabled(self.connected);self.read_btn.setEnabled(self.connected)
        self.cancel_btn.setEnabled(self.connected)
        for button in self.inputs:button.setEnabled(self.connected)
        if hasattr(self,'live_btn'):self.live_btn.setEnabled(self.connected)

    def shutdown(self):
        self._shutting_down=True;self.timer.stop();self.worker.shutdown()

    def still_running(self):
        return self.worker.isRunning() or (hasattr(self.worker,'waveform_runner') and self.worker.waveform_runner.running())
