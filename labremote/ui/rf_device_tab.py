from labremote.ui.responsive import FlowLayout
"""RF instrument panels using one common API and library-driven readouts."""
from PyQt5 import QtCore, QtWidgets
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from labremote.api.devices import device_api
from labremote.runtime.parameters import LIBRARY
from labremote.ui.widgets.step_control import StepControl, FREQUENCY_SCALES, FREQUENCY_DECIMALS
from labremote.ui.widgets.rf_layout import value_with_unit
from labremote.ui.theme import RF_INACTIVE_STYLE


class RFDeviceTab(QtWidgets.QWidget):
    log_message = QtCore.pyqtSignal(str)

    def __init__(self, family, name, host, port, parent=None):
        super().__init__(parent)
        from labremote.devices.afg2105.worker import AFG2105Worker
        from labremote.devices.sg384.worker import SG384Worker
        from labremote.devices.anapico.worker import AnaPicoWorker
        from labremote.devices.dds4.worker import DDS4Worker
        self.family,self.name,self.endpoint=family,name,(host,port)
        self.connected=False
        self.rows={};self.output_rows={};self.write_buttons=[];self.read_buttons=[]
        self.worker={'afg2105':AFG2105Worker,'sg384':SG384Worker,'anapico':AnaPicoWorker,'dds4':DDS4Worker}[family]()
        self.api=device_api(self.worker)
        root=QtWidgets.QVBoxLayout(self)
        connection=QtWidgets.QGroupBox(f'{family.upper()} — {name}')
        box=QtWidgets.QVBoxLayout(connection); buttons=FlowLayout()
        self.connect_button=QtWidgets.QPushButton('Connect')
        self.disconnect_button=QtWidgets.QPushButton('Disconnect')
        self.refresh_button=QtWidgets.QPushButton('Refresh')
        self.cancel_button=QtWidgets.QPushButton('Cancel operation / workflow')
        for widget in (self.connect_button,self.disconnect_button,self.refresh_button,self.cancel_button):buttons.addWidget(widget)
        box.addLayout(buttons)
        self.status=QtWidgets.QLabel('Disconnected');self.status.setWordWrap(True);box.addWidget(self.status)
        box.addWidget(QtWidgets.QLabel('Monitoring: every 60 s; explicit reads always query the server'))
        root.addWidget(connection)
        self.connect_button.clicked.connect(self._connect)
        self.disconnect_button.clicked.connect(lambda:self._request(self.api.disconnect))
        self.refresh_button.clicked.connect(lambda:self._request(self.api.refresh))
        self.cancel_button.clicked.connect(self.api.cancel)
        if family=='afg2105':
            grid=self._group(root,'Sine excitation · server-owned AFG2105')
            self._number(grid,'frequency','Frequency',1e6,'MHz',0.0000001,5,self.api.set_frequency)
            self._number(grid,'amplitude','Amplitude',1,'dBm',-56.020599,23.9794,self.api.set_amplitude)
            self._number(grid,'offset','DC offset',1,'V',-5,5,self.api.set_offset)
            self.rows['frequency']['editor'].setValue(1)
            self.rows['amplitude']['editor'].setValue(-20)
            row=self.rows['amplitude']
            display=QtWidgets.QComboBox();display.addItems(['dBm','Vpp'])
            display.setToolTip('UI display/input unit only; server amplitude is always Vpp')
            row['units']=display;row['unit_label'].hide();row['input_box'].layout().addWidget(display)
            row['apply'].clicked.disconnect()
            row['apply'].clicked.connect(self._afg_apply_amplitude)
            display.currentTextChanged.connect(self._afg_amplitude_unit)

            self._output(grid,'output',self.api)
            grid=self._group(root,'Instrument settings')
            self._readout(grid,'waveform','Waveform','')
            self._readout(grid,'amplitude_unit','Instrument amplitude unit','')
            unit_row=grid.rowCount()
            self.afg_unit_choice=QtWidgets.QComboBox()
            self.afg_unit_choice.addItem('Select unit...',None)
            for label,code in [('dBm','DBM'),('Vpp','VPP'),('Vrms','VRMS')]:
                self.afg_unit_choice.addItem(label,code)
            self.afg_unit_apply=QtWidgets.QPushButton('Apply unit')
            self.afg_unit_read=QtWidgets.QPushButton('Read unit')
            self.afg_unit_apply.clicked.connect(self._afg_apply_unit)
            self.afg_unit_read.clicked.connect(lambda:self._request(self.api.acquire,'amplitude_unit'))
            grid.addWidget(QtWidgets.QLabel('Change instrument unit'),unit_row,0)
            grid.addWidget(self.afg_unit_choice,unit_row,2)
            grid.addWidget(self.afg_unit_apply,unit_row,4)
            grid.addWidget(self.afg_unit_read,unit_row,5)
            self.write_buttons.append(self.afg_unit_apply);self.read_buttons.append(self.afg_unit_read)

            self._readout(grid,'load_impedance','Load setting','')
            note='Server amplitude is always Vpp. The amplitude selector controls UI input/display (dBm assumes sine / 50 Ω), independently of instrument unit. Driver 0.4.0+ required. The server driver enforces its configured power limit and amplitude/offset limits. Connect and Disconnect preserve output; use RF OFF to disable it.'
        elif family=='sg384':
            grid=self._group(root,'Shared frequency and phase — BNC / N')
            self._number(grid,'frequency','Frequency',1e6,'MHz',0,4050,self.api.set_frequency)
            self._number(grid,'phase','Phase',1,'deg',-360,360,self.api.set_phase)
            for port in ('BNC','N'):
                api=device_api(self.worker,channel=port); prefix=port.lower()
                grid=self._group(root,port+' output')
                self._number(grid,prefix+'_power_dbm','Power',1,'dBm',-110,20,api.set_power)
                path=prefix+'_power_dbm';row=self.rows[path]
                units=QtWidgets.QComboBox();units.addItems(['dBm','Vpp']);row['units']=units
                units.setFixedWidth(72)
                row['unit_label'].hide()
                row['input_box'].layout().addWidget(units)
                row['apply'].clicked.disconnect()
                row['apply'].clicked.connect(lambda _=False,p=path,a=api:self._request(a.set_power,self.rows[p]['editor'].value(),unit=self.rows[p]['units'].currentText()))
                units.currentTextChanged.connect(lambda unit,p=path:self._sg_power_unit(p,unit))
                step_units=QtWidgets.QComboBox();step_units.addItems(['dBm','Vpp']);step_units.setFixedWidth(60)
                row['step_units']=step_units;row['step'].unit_label.hide();row['step'].layout().addWidget(step_units)
                step_units.currentTextChanged.connect(units.setCurrentText)
                units.currentTextChanged.connect(step_units.setCurrentText)
                self._readout(grid,prefix+'_power_vpp','Voltage (from dBm)','Vpp')
                from labremote.configuration.device_config import load_rf_device_config,sg_power_cap_dbm,dbm_to_vpp
                config=load_rf_device_config('sg384',name)
                cap=sg_power_cap_dbm(config,port)
                limit=QtWidgets.QLabel('Configured limit: none (instrument bounds still apply)' if cap is None else
                                      f'Configured limit: {dbm_to_vpp(cap):.9g} Vpp / {cap:.6g} dBm (50 ohm)')
                grid.addWidget(limit,grid.rowCount(),0,1,7)
                row['limit']=limit
                units.setCurrentText(config.get('display',{}).get('power_unit','dBm'))
                self._output(grid,prefix+'_output',api)
            grid=self._group(root,'Reference — selected timebase')
            self._readout(grid,'timebase_code','Timebase code','0 Crystal / 1 OCXO / 2 Rubidium / 3 External')
            self._readout(grid,'reference_events','Historical unlock events','read-to-clear')
            events=QtWidgets.QPushButton('Read historical reference events (clears flags)')
            events.clicked.connect(self._reference_events);grid.addWidget(events,grid.rowCount(),0,1,5)
            self.read_buttons.append(events)
            note='SG384 timebase selection does not verify the physical PLL LOCK LED.'
        elif family=='anapico':
            grid=self._group(root,'RF output — frequency and phase')
            self._number(grid,'frequency','Frequency',1e6,'MHz',10,20000,self.api.set_frequency)
            self._number(grid,'phase','Phase',1,'deg',-360,360,self.api.set_phase)
            self._output(grid,'output',self.api)
            grid=self._group(root,'Reference input')
            self._readout(grid,'reference_source','Source','')
            self._number(grid,'external_lock_frequency','External reference',1e6,'MHz',1,250,self.api.set_external_reference)
            self._readout(grid,'locked','Reference lock','')
            internal=QtWidgets.QPushButton('Internal reference');internal.clicked.connect(lambda:self._request(self.api.set_internal_reference))
            grid.addWidget(internal,grid.rowCount(),0,1,5);self.write_buttons.append(internal)
            grid=self._group(root,'Reference output')
            self._readout(grid,'reference_output_frequency','Frequency','Hz')
            self._readout(grid,'reference_output_enabled','Enabled','')
            self.ref_out_freq=QtWidgets.QComboBox();self.ref_out_freq.addItems(['10 MHz','100 MHz'])
            self.ref_out_enabled=QtWidgets.QCheckBox('Enable REF OUT')
            apply=QtWidgets.QPushButton('Apply REF OUT')
            apply.clicked.connect(lambda:self._request(self.api.set_reference_output,
                10e6 if self.ref_out_freq.currentIndex()==0 else 100e6,self.ref_out_enabled.isChecked()))
            row=grid.rowCount();grid.addWidget(self.ref_out_freq,row,0);grid.addWidget(self.ref_out_enabled,row,1);grid.addWidget(apply,row,4)
            self.write_buttons.append(apply)
            note='APSYN420 has fixed RF power; there is no power setpoint.'
        else:
            for channel in range(1,5):
                api=device_api(self.worker,channel=channel);prefix=f'ch{channel}.'
                grid=self._group(root,f'CH {channel}')
                self._number(grid,prefix+'frequency_hz','Frequency',1e6,'MHz',10,400,api.set_frequency)
                self._number(grid,prefix+'phase_deg','Phase',1,'deg',0,360,api.set_phase)
                self._number(grid,prefix+'vva_level','VVA level',1,'',0,1000,api.set_vva,integer=True)
                self._output(grid,prefix+'output_enabled',api)
            self.all_off_button=QtWidgets.QPushButton('All channels OFF')
            self.all_off_button.clicked.connect(lambda:self._request(self.api.all_off))
            self.write_buttons.append(self.all_off_button);root.addWidget(self.all_off_button)
            note='DDS: 마지막 전송 설정이며 실제 RF readback이 아닙니다. 미확인 값은 — 로 표시합니다.'
        label=QtWidgets.QLabel(note);label.setWordWrap(True);root.addWidget(label)
        self.message=QtWidgets.QLabel('');self.message.setWordWrap(True);root.addWidget(self.message)
        root.addStretch()
        self.worker.connected.connect(self._connected)
        self.worker.disconnected.connect(self._disconnected)
        self.worker.snapshot.connect(self._snapshot)
        self.worker.failure.connect(self._failure)
        self.worker.completed.connect(self._completed)
        self.worker.handle_changed.connect(lambda _:self._controls())
        self.worker.busy_changed.connect(lambda _:self._controls())
        self.timer=QtCore.QTimer(self);self.timer.setInterval(60000);self.timer.timeout.connect(self._poll);self.timer.start()
        self._controls();self.worker.start()

    def _afg_apply_amplitude(self):
        from labremote.configuration.device_config import dbm_to_vpp
        row=self.rows['amplitude'];value=row['editor'].value()
        if row['unit']=='dBm':value=dbm_to_vpp(value)
        return self._request(self.api.set_amplitude,value)

    def _afg_amplitude_unit(self,unit):
        from labremote.configuration.device_config import dbm_to_vpp,vpp_to_dbm
        row=self.rows['amplitude'];editor=row['editor']
        if unit==row['unit']:return
        value=dbm_to_vpp(editor.value()) if unit=='Vpp' else vpp_to_dbm(editor.value())
        editor.setDecimals(9 if unit=='Vpp' else 6)
        editor.setRange(*self._input_bounds('amplitude',1,unit,editor.decimals()))
        editor.setValue(value);row['unit']=unit
        row['step'].saved.setdefault('Vpp',.001);row['step'].change_unit(unit)
        self._snapshot({},'DISPLAY_UNIT')

    def _afg_apply_unit(self):
        unit=self.afg_unit_choice.currentData()
        if unit is not None:return self._request(self.api.set_amplitude_unit,unit)

    def _group(self, root, title):
        box=QtWidgets.QGroupBox(title);grid=QtWidgets.QGridLayout(box);grid.setColumnStretch(6,1);root.addWidget(box);return grid

    def _number(self, grid, path, title, scale, unit, low, high, setter, integer=False):
        row=grid.rowCount();read=QtWidgets.QLabel('— '+unit);read.setMinimumWidth(130)
        editor=QtWidgets.QSpinBox() if integer else QtWidgets.QDoubleSpinBox()
        if not integer:editor.setDecimals(7 if self.family=='afg2105' and path=='frequency' else 6)
        low,high=self._input_bounds(path,scale,unit,0 if integer else editor.decimals())
        if integer:low,high=int(low),int(high)
        editor.setRange(low,high);editor.setMinimumWidth(125)
        apply=QtWidgets.QPushButton('Apply');apply.clicked.connect(lambda:self._request(setter,editor.value()*self.rows[path]['scale']))
        read_btn=QtWidgets.QPushButton('Read');read_btn.clicked.connect(lambda:self._request(self.api.acquire,path))
        if integer:
            step=QtWidgets.QSpinBox();step.setRange(1,1000);step.setValue(1);step.setPrefix('Step ');step.valueChanged.connect(editor.setSingleStep)
        else:step=StepControl(editor,unit)
        unit_label=QtWidgets.QLabel(unit);input_box=value_with_unit(editor,unit_label)
        for col,widget in enumerate((QtWidgets.QLabel(title),read,input_box,step,apply,read_btn)):grid.addWidget(widget,row,col)
        step.setMaximumWidth(270);input_box.setMaximumWidth(240);apply.setMaximumWidth(100);read_btn.setMaximumWidth(80)
        self.rows[path]=dict(label=read,editor=editor,scale=scale,unit=unit,apply=apply,read=read_btn,step=step,grid_row=row,input_box=input_box,unit_label=unit_label)
        if unit=='MHz':
            choices=['MHz','kHz','Hz'] if self.family in ('sg384','afg2105') else ['GHz','MHz','kHz','Hz']
            units=QtWidgets.QComboBox();units.addItems(choices);units.setCurrentText(unit);units.setFixedWidth(60)
            unit_label.hide();input_box.layout().addWidget(units);self.rows[path]['units']=units
            step.enable_frequency_units(choices)
            units.currentTextChanged.connect(lambda u,p=path:self._frequency_unit(p,u))
        self.write_buttons.append(apply);self.read_buttons.append(read_btn)

    def _readout(self,grid,path,title,unit):
        row=grid.rowCount();label=QtWidgets.QLabel('—');grid.addWidget(QtWidgets.QLabel(title),row,0);grid.addWidget(label,row,1,1,4)
        self.rows[path]=dict(label=label,scale=1,unit=unit)

    def _output(self,grid,path,api):
        row=grid.rowCount();label=QtWidgets.QLabel('Output: UNKNOWN')
        on=QtWidgets.QPushButton('RF ON');off=QtWidgets.QPushButton('RF OFF')
        on.clicked.connect(lambda:self._request(api.on));off.clicked.connect(lambda:self._request(api.off))
        grid.addWidget(label,row,0,1,2);grid.addWidget(on,row,2);grid.addWidget(off,row,4)
        on.setStyleSheet(RF_INACTIVE_STYLE)
        self.output_rows[path]=(label,on,off);self.write_buttons.extend((on,off))

    def _input_bounds(self,path,scale,unit,decimals):
        from labremote.runtime.parameters import registry
        from labremote.configuration.device_config import load_rf_device_config,sg_power_cap_dbm,dbm_to_vpp
        spec=registry().get(self.family,path)
        low,high=spec.minimum,spec.maximum
        if self.family=='afg2105' and path=='amplitude' and unit=='dBm':
            from labremote.configuration.device_config import vpp_to_dbm
            low,high=vpp_to_dbm(low),vpp_to_dbm(high)

        if self.family=='sg384' and path.endswith('_power_dbm'):
            cap=sg_power_cap_dbm(load_rf_device_config('sg384',self.name),path.split('_')[0].upper())
            if cap is not None:high=min(high,cap)
            if unit=='Vpp':low,high=dbm_to_vpp(low),dbm_to_vpp(high)
        # Round inward so the spinbox never rounds a limit into an invalid value.
        quantum=Decimal(1).scaleb(-decimals)
        low=float((Decimal(str(low))/Decimal(str(scale))).quantize(quantum,rounding=ROUND_CEILING))
        high=float((Decimal(str(high))/Decimal(str(scale))).quantize(quantum,rounding=ROUND_FLOOR))
        return low,high

    def _sg_power_unit(self,path,unit):
        from labremote.configuration.device_config import dbm_to_vpp,vpp_to_dbm
        row=self.rows[path];editor=row['editor'];old=row['unit']
        if unit==old:return
        value=dbm_to_vpp(editor.value()) if unit=='Vpp' else vpp_to_dbm(editor.value())
        editor.setDecimals(9 if unit=='Vpp' else 6)
        editor.setRange(*self._input_bounds(path,1,unit,editor.decimals()))
        editor.setValue(value)
        row['step'].saved.setdefault('Vpp',.01)
        row['step'].change_unit(unit)
        row['unit']=unit
        if hasattr(self,'message'):self._snapshot({},'UNIT')
        else:row['label'].setText('— '+unit)

    def _frequency_unit(self,path,unit):
        row=self.rows[path];editor=row['editor'];scale=FREQUENCY_SCALES[unit]
        value=editor.value()*row['scale']/scale
        editor.setDecimals(FREQUENCY_DECIMALS[unit])
        editor.setRange(*self._input_bounds(path,scale,unit,editor.decimals()))
        editor.setValue(value);row['scale']=scale;row['unit']=unit
        row['step'].set_target_unit(unit)
        if hasattr(self,'message'):self._snapshot({},'UNIT')

    def _request(self, method, *args, **kwargs):
        handle=method(*args, **kwargs)
        self._controls()
        return handle

    def _connect(self):
        endpoint=self.endpoint_provider() if hasattr(self,'endpoint_provider') else self.endpoint
        return self._request(self.api.connect,*endpoint,self.name)

    def _connected(self, info):
        self.connected=True;self.status.setText('Connected: '+str(info.get('idn',self.name)))
        self._request(self.api.refresh)

    def _disconnected(self, message):
        self.connected=False;self.status.setText(message);self._snapshot({},'DISCONNECT');self._controls()

    def _reference_events(self):
        if QtWidgets.QMessageBox.question(self,'Read-to-clear events','Read and clear historical PLL unlock flags?',
                QtWidgets.QMessageBox.Yes|QtWidgets.QMessageBox.No,QtWidgets.QMessageBox.No)==QtWidgets.QMessageBox.Yes:
            self._request(self.api.read_reference_events)

    def _poll(self):
        if self.connected and not self.worker.connection_error:return self.api.auto_monitor()

    def _controls(self):
        reserved=getattr(self.worker,'_scan_owner',None) is not None
        busy=self.worker.has_requests() or reserved;ready=self.connected and not busy
        self.connect_button.setEnabled(not self.connected and not busy)
        self.disconnect_button.setEnabled(self.connected and not reserved)
        self.refresh_button.setEnabled(ready);self.cancel_button.setEnabled(busy)
        for button in self.write_buttons+self.read_buttons:button.setEnabled(ready)
        if self.family=='dds4':
            status=LIBRARY.read((self.worker._execution_device,'status_json'))
            if status.quality!='valid' or not status.observed or status.observed.get('faulted') or not status.observed.get('connected'):
                for button in self.write_buttons:button.setEnabled(False)

    def _snapshot(self, data, action):
        # Always project the latest library, including when queued snapshots arrive late.
        states={path:state for (identity,path),state in LIBRARY.snapshot().items() if identity==self.worker._execution_device}
        def valid(state):
            return self.connected and state is not None and state.quality=='valid' and state.verification not in ('failed','pending','mismatch')
        for path,row in self.rows.items():
            state=states.get(path)
            value=state.observed if valid(state) else None
            if self.family=='afg2105' and path=='amplitude' and row['unit']=='dBm' and value is not None:
                from labremote.configuration.device_config import vpp_to_dbm
                try:value=vpp_to_dbm(value)
                except ValueError:value=None
            if self.family=='sg384' and path.endswith('_power_vpp'):
                from labremote.configuration.device_config import dbm_to_vpp
                state=states.get(path.replace('_power_vpp','_power_dbm'))
                value=dbm_to_vpp(state.observed) if valid(state) else None
            elif self.family=='sg384' and path.endswith('_power_dbm') and row['unit']=='Vpp' and value is not None:
                from labremote.configuration.device_config import dbm_to_vpp
                value=dbm_to_vpp(value)
            if value is None:text='— '+row['unit']
            elif isinstance(value,(int,float)) and not isinstance(value,bool):text=f"{value/row['scale']:.9g} {row['unit']}"
            else:text=str(value)+' '+row['unit']
            row['label'].setText(text);row['label'].setToolTip(state.error or '' if state else '')
        for path,(label,on,off) in self.output_rows.items():
            state=states.get(path);value=state.observed if valid(state) else None
            label.setText('Output: UNKNOWN' if value is None else 'Output: '+('ON' if value else 'OFF'))
            on.setText('RF ON ✓' if value else 'RF ON')
            on.setStyleSheet('QPushButton {background-color:#20554f;color:#9ef1df;font-weight:bold;}' if value else RF_INACTIVE_STYLE)
        if self.family=='dds4':
            state=states.get('status_json')
            if valid(state) and (state.observed.get('faulted') or not state.observed.get('connected')):
                self.status.setText('DDS disconnected / faulted — recover server device')
                for label,on,off in self.output_rows.values():
                    label.setText('Output: UNKNOWN');on.setText('RF ON');on.setStyleSheet(RF_INACTIVE_STYLE)
        self._controls()

    def _failure(self, action, message):
        self.message.setText(f'{action}: {message}');self.log_message.emit(f'[{self.name}] {action}: {message}')
        self._snapshot({},'ERROR')
        alarm=QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning,self.name+' — '+action,message,parent=self)
        alarm.setAttribute(QtCore.Qt.WA_DeleteOnClose);alarm.open()

    def _completed(self,action):
        self.message.setText(action+': completed');self._controls()

    def shutdown(self):self.timer.stop();self.worker.shutdown()
    def still_running(self):return self.worker.isRunning()
