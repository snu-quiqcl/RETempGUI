"""DS1052E plots and controls, using the same API and worker queue as workflows."""
import math
from collections import deque
import numpy as np
from PyQt5 import QtCore, QtWidgets
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from labremote.api.devices import device_api
from labremote.runtime.parameters import LIBRARY
from labremote.ui.widgets.readback_inputs import add_readback_button
from labremote.devices.ds1052e.worker import DS1052EWorker

COLORS={'CH1':'#f3c46b','CH2':'#76baff','CH3':'#df80e8','CH4':'#79df96'}


class DS1052ETab(QtWidgets.QWidget):
    channels=('CH1','CH2')
    worker_type=DS1052EWorker
    scope_title='DS1052E two-channel screen acquisition'
    sample_note='600 LCD samples/channel, not deep memory'
    display_on='ON'
    trigger_mode_path='trigger_mode'
    trigger_sweep_path='trigger_sweep'
    first_measurement='frequency'
    first_measurement_title='Frequency'
    first_measurement_unit='Hz'
    slopes=('POS','NEG')
    sweeps=('AUTO','NORM','SING')
    shared_waveform_path=None
    log_message=QtCore.pyqtSignal(str)

    def __init__(self,name,host,port,parent=None):
        super().__init__(parent)
        self.device_name=name
        self._host,self._port=host,int(port)
        self.connected=False
        self.live=False
        self.latest={};self.traces={};self.trace_scales={};self.trace_timebase={}
        self._seen=deque(maxlen=128)
        self._last_waveform_completion=0
        self.worker=self.worker_type();self.api=device_api(self.worker)
        self._build()
        self.worker.connected.connect(self._connected)
        self.worker.disconnected.connect(self._disconnected)
        self.worker.snapshot.connect(self._settings)
        self.worker.handle_changed.connect(self._handle_changed)
        self.worker.busy_changed.connect(lambda _:self._buttons())
        self.worker.failure.connect(self._failed)
        self.worker.waveform_changed.connect(self._waveform_changed)
        self.worker.start()
        self.monitor_timer=QtCore.QTimer(self);self.monitor_timer.setInterval(60000)
        self.monitor_timer.timeout.connect(self._poll);self.monitor_timer.start()

    def _build(self):
        root=QtWidgets.QVBoxLayout(self)
        self.ds1052e_load_inputs_button = add_readback_button(
            self, root, '_load_inputs_requested', lambda: self.connected and not self.worker.has_requests(), self.api.refresh)
        line=QtWidgets.QHBoxLayout()
        self.connect_btn=QtWidgets.QPushButton('Connect')
        self.disconnect_btn=QtWidgets.QPushButton('Disconnect')
        self.refresh_btn=QtWidgets.QPushButton('Read settings')
        self.status=QtWidgets.QLabel('Not connected')
        line.addWidget(QtWidgets.QLabel(self.device_name))
        for x in (self.connect_btn,self.disconnect_btn,self.refresh_btn):line.addWidget(x)
        line.addWidget(self.status,1)
        root.addLayout(line)
        self.cancel_btn=QtWidgets.QPushButton("Cancel operation / workflow")
        line.addWidget(self.cancel_btn)
        self.cancel_btn.clicked.connect(self.api.cancel)
        self.connect_btn.clicked.connect(self._connect)
        self.disconnect_btn.clicked.connect(self._disconnect_request)
        self.refresh_btn.clicked.connect(self.api.refresh)

        box=QtWidgets.QGroupBox('Waveform — '+self.scope_title)
        gl=QtWidgets.QGridLayout(box)
        self.ch_checks={}
        for i,ch in enumerate(self.channels):
            cb=QtWidgets.QCheckBox(ch+' scope display')
            cb.toggled.connect(lambda val,channel=ch:self.api.set_channel_display(channel,bool(val)))
            gl.addWidget(cb,0,i);self.ch_checks[ch]=cb
        self.fetch_once=QtWidgets.QPushButton('Fetch once')
        self.live_btn=QtWidgets.QPushButton('Start live waveform')
        self.period=QtWidgets.QSpinBox()
        self.period.setRange(250,15000);self.period.setValue(1000);self.period.setSuffix(' ms')
        gl.addWidget(self.fetch_once,1,0)
        gl.addWidget(self.live_btn,1,1)
        gl.addWidget(QtWidgets.QLabel('Interval'),1,2)
        gl.addWidget(self.period,1,3)
        self.fetch_once.clicked.connect(self._fetch)
        self.live_btn.clicked.connect(self._toggle_live)
        self.trigger_readback=QtWidgets.QLabel('Trigger: —')
        self.wave_info=QtWidgets.QLabel('Screen waveform: '+self.sample_note+'. Readback unchanged on Connect.')
        self.wave_info.setWordWrap(True)
        gl.addWidget(self.trigger_readback,2,0,1,4)
        gl.addWidget(self.wave_info,3,0,1,4)
        root.addWidget(box)

        self.fig=Figure(figsize=(9.2,4.4),dpi=95)
        self.canvas=FigureCanvasQTAgg(self.fig)
        self.canvas.setMinimumHeight(330)
        root.addWidget(self.canvas,1)
        self._render()

        settings=QtWidgets.QGridLayout()
        timebox=QtWidgets.QGroupBox('Time range / horizontal scale')
        g=QtWidgets.QGridLayout(timebox)
        self.time_div=self._text('0.001')
        self.time_offset=self._text('0')
        self.time_apply=QtWidgets.QPushButton('Apply Time/Div + offset')
        self.time_read=QtWidgets.QLabel('—')
        g.addWidget(QtWidgets.QLabel('Time/div (s)'),0,0);g.addWidget(self.time_div,0,1)
        g.addWidget(QtWidgets.QLabel('Time offset (s)'),1,0);g.addWidget(self.time_offset,1,1)
        g.addWidget(self.time_apply,2,0,1,2);g.addWidget(self.time_read,3,0,1,2)
        self.time_apply.clicked.connect(self._apply_horizontal)
        settings.addWidget(timebox,0,0)

        # CH1 and CH2 have independent physical V/div and offset settings.
        # Separate controls prevent accidentally editing the other channel.
        volts=QtWidgets.QGroupBox('Amplitude range / vertical scale (physical scope)')
        g=QtWidgets.QGridLayout(volts)
        self.vert_div={}
        self.vert_off={}
        self.vert_apply={}
        self.vert_read={}
        for col,ch in enumerate(self.channels):
            offset=3*col
            ch_label=QtWidgets.QLabel(ch)
            ch_label.setStyleSheet('color: '+COLORS[ch]+'; font-weight: 600;')
            g.addWidget(ch_label,0,offset,1,2)
            self.vert_div[ch]=self._text('1.0')
            self.vert_off[ch]=self._text('0')
            self.vert_apply[ch]=QtWidgets.QPushButton('Apply '+ch)
            self.vert_read[ch]=QtWidgets.QLabel(ch+' readback: —')
            self.vert_read[ch].setWordWrap(True)
            g.addWidget(QtWidgets.QLabel('V/div (V)'),1,offset)
            g.addWidget(self.vert_div[ch],1,offset+1)
            g.addWidget(QtWidgets.QLabel('Offset (V)'),2,offset)
            g.addWidget(self.vert_off[ch],2,offset+1)
            g.addWidget(self.vert_apply[ch],3,offset,1,2)
            g.addWidget(self.vert_read[ch],4,offset,1,2)
            self.vert_apply[ch].clicked.connect(
                lambda _checked=False,channel=ch:self._apply_vertical(channel))
            if col==0:
                g.setColumnMinimumWidth(2,12)
        settings.addWidget(volts,0,1)

        trigger=QtWidgets.QGroupBox('Trigger threshold / acquisition')
        g=QtWidgets.QGridLayout(trigger)
        self.trigger_ch=QtWidgets.QComboBox();self.trigger_ch.addItems(self.channels)
        self.trigger_level=self._text('0.0')
        self.trigger_slope=QtWidgets.QComboBox();self.trigger_slope.addItems(self.slopes)
        self.trigger_sweep=QtWidgets.QComboBox();self.trigger_sweep.addItems(self.sweeps)
        self.trigger_apply=QtWidgets.QPushButton('Apply Edge Trigger')
        self.run_scope=QtWidgets.QPushButton('Scope RUN')
        self.stop_scope=QtWidgets.QPushButton('Scope STOP')
        g.addWidget(QtWidgets.QLabel('Source'),0,0);g.addWidget(self.trigger_ch,0,1)
        g.addWidget(QtWidgets.QLabel('Level / threshold (V)'),1,0);g.addWidget(self.trigger_level,1,1)
        g.addWidget(QtWidgets.QLabel('Slope'),2,0);g.addWidget(self.trigger_slope,2,1)
        g.addWidget(QtWidgets.QLabel('Sweep'),3,0);g.addWidget(self.trigger_sweep,3,1)
        g.addWidget(self.trigger_apply,4,0,1,2)
        g.addWidget(self.run_scope,5,0);g.addWidget(self.stop_scope,5,1)
        self.trigger_apply.clicked.connect(self._apply_trigger)
        self.run_scope.clicked.connect(lambda:self._scope_run(True))
        self.stop_scope.clicked.connect(lambda:self._scope_run(False))
        settings.addWidget(trigger,1,0)

        measures=QtWidgets.QGroupBox('Instrument-calculated measurements (read-only)')
        g=QtWidgets.QGridLayout(measures)
        self.freq_read={};self.vpp_read={}
        for i,ch in enumerate(self.channels):
            freq=QtWidgets.QLabel('—'); vpp=QtWidgets.QLabel('—')
            g.addWidget(QtWidgets.QLabel(ch),i,0)
            g.addWidget(QtWidgets.QLabel(self.first_measurement_title),i,1);g.addWidget(freq,i,2)
            g.addWidget(QtWidgets.QLabel('Vpp'),i,3);g.addWidget(vpp,i,4)
            self.freq_read[ch]=freq;self.vpp_read[ch]=vpp
        label=QtWidgets.QLabel('Frequency/Vpp are estimates measured by the oscilloscope, not settable output values. '
           'Read settings updates the values; Monitoring refreshes settings every 60 seconds.')
        label.setWordWrap(True)
        g.addWidget(label,2,0,1,5)
        settings.addWidget(measures,1,1)
        root.addLayout(settings)

        viewing=QtWidgets.QGroupBox('Graph display mode (does NOT change the scope)')
        g=QtWidgets.QGridLayout(viewing)
        self.plot_mode=QtWidgets.QComboBox()
        self.plot_mode.addItems((
            'Follow physical V/div (8 vertical divisions)',
            'Fit each waveform (autoscale)',
            'Manual graph limits',
        ))
        self.plot_mode.currentIndexChanged.connect(lambda _index:self._render())
        g.addWidget(QtWidgets.QLabel('Graph mode'),0,0)
        g.addWidget(self.plot_mode,0,1,1,3)
        note=QtWidgets.QLabel(
            'Follow V/div reproduces the oscilloscope vertical display. '
            'Fit waveform rescales the graph to the observed voltage and can '
            'hide V/div changes.')
        note.setWordWrap(True)
        g.addWidget(note,1,0,1,4)
        self.x_min=self._text('-0.006');self.x_max=self._text('0.006')
        self.y_min={ch:self._text('-4') for ch in self.channels}
        self.y_max={ch:self._text('4') for ch in self.channels}
        self.plot_apply=QtWidgets.QPushButton('Apply manual graph limits')
        self.plot_apply.clicked.connect(self._render)
        g.addWidget(QtWidgets.QLabel('X min (s)'),2,0)
        g.addWidget(self.x_min,2,1)
        g.addWidget(QtWidgets.QLabel('X max (s)'),2,2)
        g.addWidget(self.x_max,2,3)
        for row,ch in enumerate(self.channels,start=3):
            for col,title in ((0,ch+' Y min (V)'),(2,ch+' Y max (V)')):
                lab=QtWidgets.QLabel(title)
                lab.setStyleSheet('color: '+COLORS[ch]+';')
                g.addWidget(lab,row,col)
            g.addWidget(self.y_min[ch],row,1)
            g.addWidget(self.y_max[ch],row,3)
        g.addWidget(self.plot_apply,3+len(self.channels),0,1,2)
        root.addWidget(viewing)
        self._buttons()

    @staticmethod
    def _text(value):
        field=QtWidgets.QLineEdit(str(value));field.setMinimumWidth(90);return field

    @staticmethod
    def _parse(widget,label):
        try:return float(widget.text())
        except ValueError:raise ValueError(f'{label} must be numeric')

    def _connect(self):
        endpoint=self.endpoint_provider() if hasattr(self,'endpoint_provider') else (self._host,self._port)
        return self.api.connect(*endpoint,self.device_name)

    def _disconnect_request(self):
        self.live=False;self.live_btn.setText('Start live waveform')
        return self.api.disconnect()

    def _apply_horizontal(self):
        try:return self.api.configure_horizontal(self._parse(self.time_div,'Time/div'),self._parse(self.time_offset,'Time offset'))
        except ValueError as error:self.status.setText(str(error))

    def _apply_vertical(self,channel):
        try:return self.api.configure_vertical(channel,self._parse(self.vert_div[channel],'V/div'),self._parse(self.vert_off[channel],'Offset'))
        except ValueError as error:self.status.setText(str(error))

    def _apply_trigger(self):
        try:return self.api.configure_trigger(self.trigger_ch.currentText(),self._parse(self.trigger_level,'Trigger level'),slope=self.trigger_slope.currentText(),sweep=self.trigger_sweep.currentText())
        except ValueError as error:self.status.setText(str(error))

    def _scope_run(self,enabled):return self.api.run() if enabled else self.api.stop()

    def _buttons(self):
        busy=self.worker.has_requests()
        self.connect_btn.setEnabled(not self.connected and not busy)
        self.disconnect_btn.setEnabled(self.connected)
        for widget in (self.refresh_btn,self.fetch_once,self.time_apply,*self.vert_apply.values(),self.trigger_apply,
                       self.run_scope,self.stop_scope,*self.ch_checks.values()):widget.setEnabled(self.connected and not busy)
        repeat=self.worker.waveform_runner.handle
        stopping=repeat is not None and not repeat.done.is_set() and repeat.status=='stopping'
        self.live_btn.setEnabled(self.connected and not stopping)
        self.period.setEnabled(not self.live)
        self.cancel_btn.setEnabled((busy or self.live) and not stopping)

    def _fetch(self):
        if not self.connected:return
        channels=tuple(ch for ch,cb in self.ch_checks.items() if cb.isChecked())
        if not channels:
            self.live=False;self.live_btn.setText('Start live waveform')
            self.wave_info.setText('No displayed channels. Enable CH1 and/or CH2 first.')
            return
        return self.api.read_waveforms(channels)

    def _toggle_live(self):
        repeat=self.worker.waveform_runner.handle
        if repeat is not None and not repeat.done.is_set():
            self.api.stop_waveform()
        else:
            channels=tuple(ch for ch,cb in self.ch_checks.items() if cb.isChecked())
            self.api.start_waveform(channels,interval_s=self.period.value()/1000)

    def _waveform_changed(self,handle):
        if handle is not self.worker.waveform_runner.handle:return
        self.live=not handle.done.is_set()
        self.live_btn.setText('Stopping waveform...' if handle.status=='stopping' else
                             'Stop live waveform' if self.live else 'Start live waveform')
        self.status.setText('WAVEFORM: '+handle.status)
        self._buttons()

    def _poll(self):
        if self.connected and not self.worker.connection_error:return self.api.monitor()

    def _connected(self,info):
        self.connected=True;self.status.setText(str(info.get('idn','DS1052E')))
        self._load_inputs_requested=True
        self.api.refresh()

    def _disconnected(self,message):
        self.connected=False;self.live=False;self.live_btn.setText('Start live waveform')
        self.traces.clear();self.trace_scales.clear();self.status.setText(message)
        self._settings({},'DISCONNECT');self._render();self._buttons()

    def _settings(self,data,source):
        # Ignore delayed payloads and use the latest validated library observations.
        plotted=set(self.traces)
        states={path:state for (device,path),state in LIBRARY.snapshot().items() if device==self.worker._execution_device}
        def value(path):
            state=states.get(path)
            if not self.connected or state is None or state.quality!='valid' or state.verification in ('pending','failed','mismatch'):return None
            return state.observed
        latest=dict(time_scale_s=value('time_scale'),time_offset_s=value('time_offset'),
                    trigger_mode=value(self.trigger_mode_path),trigger_status=value('trigger_status'),channels={})
        if self.traces and (latest['time_scale_s']!=self.trace_timebase.get('scale') or latest['time_offset_s']!=self.trace_timebase.get('offset')):
            self.traces.clear();self.trace_scales.clear()
        self.latest=latest
        self.time_read.setText(f"Readback: {latest['time_scale_s']} s/div; offset {latest['time_offset_s']} s")
        self.trigger_readback.setText(f"Trigger: {latest['trigger_mode']} / {latest['trigger_status']} / {value('trigger_source')} / {value('trigger_level')} V")
        fill=source=='REFRESH' and getattr(self,'_load_inputs_requested',False)
        if fill:
            for widget,path in [(self.time_div,'time_scale'),(self.time_offset,'time_offset'),(self.trigger_level,'trigger_level')]:
                if value(path) is not None:widget.setText(str(value(path)))
            selected=value('trigger_source')
            if selected in tuple('CHAN'+ch[-1] for ch in self.channels):self.trigger_ch.setCurrentText('CH'+selected[-1])
            for combo,path in [(self.trigger_slope,'trigger_slope'),(self.trigger_sweep,self.trigger_sweep_path)]:
                if value(path) is not None:combo.setCurrentText(value(path))
        for channel in self.channels:
            prefix=channel.lower()+'_';scale=value(prefix+'scale');offset=value(prefix+'offset')
            latest['channels'][channel]=dict(scale_vdiv=scale,offset_v=offset)
            self.vert_read[channel].setText(f'{channel}: {scale} V/div; offset {offset} V')
            self.vert_read[channel].setToolTip('; '.join(states[p].error or '' for p in (prefix+'scale',prefix+'offset') if p in states))
            display=value(prefix+'display');cb=self.ch_checks[channel]
            blocked=cb.blockSignals(True);cb.setChecked(display==self.display_on);cb.blockSignals(blocked)
            cb.setText(channel+' scope display'+(' (unknown)' if display is None else ''))
            calibration=self.trace_scales.get(channel,{})
            if display!=self.display_on or (channel in self.traces and (scale!=calibration.get('vdiv') or offset!=calibration.get('offset'))):
                self.traces.pop(channel,None);self.trace_scales.pop(channel,None)
            if fill:
                if scale is not None:self.vert_div[channel].setText(str(scale))
                if offset is not None:self.vert_off[channel].setText(str(offset))
            for field,label,unit in [(self.first_measurement,self.freq_read[channel],self.first_measurement_unit),('vpp',self.vpp_read[channel],'V')]:
                measured=value(prefix+field);label.setText('Unavailable' if measured is None else f'{measured:.8g} {unit}')
        if source=='REFRESH':self._load_inputs_requested=False
        if set(self.traces)!=plotted:self._render()
        self._buttons()

    def _handle_changed(self,handle):
        self._buttons()
        if not handle.done.is_set() or handle.request_id in self._seen:return
        self._seen.append(handle.request_id)
        if handle.action=='FETCH':
            run_id=handle.arguments.get('waveform_run_id')
            repeat=self.worker.waveform_runner.handle
            if run_id and (repeat is None or repeat.request_id!=run_id or repeat.done.is_set() or repeat.cancelled()):return
            if handle.completed_at_ns < self._last_waveform_completion:return
            self._last_waveform_completion=handle.completed_at_ns
            if handle.error is None:
                result=handle.result
                states={path:state for (device,path),state in LIBRARY.snapshot().items() if device==self.worker._execution_device}
                accepted={}
                for channel,trace in result['traces'].items():
                    prefix=channel.lower()+'_'
                    expected={'time_scale':result['timebase']['scale'],'time_offset':result['timebase']['offset'],
                              prefix+'scale':result['scales'][channel]['vdiv'],prefix+'offset':result['scales'][channel]['offset'],prefix+'display':self.display_on}
                    waveform=states.get(self.shared_waveform_path or prefix+'waveform')
                    # A newer in-flight get must not hide the last completed frame.
                    # Completion ordering above prevents an old result replacing a newer displayed frame.
                    if (self.connected and waveform is not None and waveform.quality=='valid'
                        and all(path in states and states[path].quality=='valid' and states[path].verification not in ('pending','failed','mismatch')
                                and states[path].observed==value for path,value in expected.items())):
                        accepted[channel]=trace
                if result['traces'] and not accepted:
                    return  # Delayed completion must not restore an obsolete acquisition.
                self.traces=accepted;self.trace_scales={ch:result['scales'][ch] for ch in accepted}
                self.trace_timebase=result['timebase']
                self.wave_info.setText('Displaying '+self.sample_note)
            else:
                self.live=False;self.live_btn.setText('Start live waveform');self.traces.clear();self.trace_scales.clear()
            self._render()
        elif handle.action in ('VERTICAL','HORIZONTAL','CHANNEL'):
            # A changed scale or display invalidates any older plotted acquisition.
            self.traces.clear();self.trace_scales.clear();self._render()
        if handle.error is None:self.status.setText(handle.action+': completed')

    def _failed(self,action,message):
        if getattr(self,'_shutting_down',False):return
        self._load_inputs_requested=False
        self.status.setText(f'{action}: {message}');self.log_message.emit(f'[{self.device_name}] {action}: {message}')
        self._settings({},'ERROR')
        alarm=QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning,self.device_name+' — '+action,message,parent=self)
        alarm.setAttribute(QtCore.Qt.WA_DeleteOnClose);alarm.open()

    def shutdown(self):
        self._shutting_down=True
        self.live=False;self.monitor_timer.stop();self.worker.shutdown()

    def still_running(self):return self.worker.isRunning() or self.worker.waveform_runner.running()

    def _render(self):
        # Matplotlib data-autoscale is NOT oscilloscope V/div. A constant
        # 2 Vpp signal still represents 2 Vpp when its vertical sensitivity
        # changes; to reproduce zoom, set display limits from the actual
        # V/div captured alongside each waveform, not from min/max(data).
        self.fig.clear()
        ax1=self.fig.add_subplot(111)
        self.plot_axes={self.channels[0]:ax1}
        for index,ch in enumerate(self.channels[1:]):
            axis=ax1.twinx()
            axis.spines['right'].set_position(('axes',1+index*.16))
            axis.grid(False)
            self.plot_axes[ch]=axis
        ax1.set_xlabel('Time (s)')
        ax1.grid(True,alpha=.25)
        handles=[]
        for ch in self.channels:
            axis=self.plot_axes[ch]
            side='left' if ch=='CH1' else 'right'
            axis.set_ylabel(f'{ch} Voltage (V)',color=COLORS[ch])
            axis.tick_params(axis='y',colors=COLORS[ch])
            axis.spines[side].set_color(COLORS[ch])
            if ch in self.traces:
                t,v=self.traces[ch]
                h,=axis.plot(t,v,label=ch,lw=1.3,color=COLORS[ch])
                handles.append(h)
        if handles:
            ax1.legend(handles,[h.get_label() for h in handles],loc='upper right')

        mode=self.plot_mode.currentIndex() if hasattr(self,'plot_mode') else 0
        if mode==0:  # Match the physical 8-division display per channel.
            for ch,axis in self.plot_axes.items():
                item=self.trace_scales.get(ch,{})
                vdiv=item.get('vdiv')
                offset=item.get('offset')
                if vdiv is None or offset is None:
                    state=self.latest.get('channels',{}).get(ch,{})
                    vdiv=state.get('scale_vdiv')
                    offset=state.get('offset_v')
                if vdiv is None or offset is None:
                    continue
                vdiv,offset=float(vdiv),float(offset)
                if not (math.isfinite(vdiv) and vdiv>0 and math.isfinite(offset)):
                    continue
                # DS1000E 600-point LCD encoding maps byte 125 to -offset,
                # and 25 raw samples per one vertical division.
                center=-offset
                axis.set_ylim(center-4.0*vdiv,center+4.0*vdiv)
                axis.set_yticks(np.linspace(center-4*vdiv,center+4*vdiv,9))
                axis.set_ylabel(f'{ch}: {vdiv:g} V/div',color=COLORS[ch])
        elif mode==2:  # Manual graph limits, not the physical scope settings.
            try:
                xmin=self._parse(self.x_min,'X min')
                xmax=self._parse(self.x_max,'X max')
                if xmin>=xmax:
                    raise ValueError('X min must be less than X max')
                limits={}
                for ch in self.channels:
                    ymin=self._parse(self.y_min[ch],ch+' Y min')
                    ymax=self._parse(self.y_max[ch],ch+' Y max')
                    if ymin>=ymax:
                        raise ValueError(ch+' Y min must be less than Y max')
                    limits[ch]=(ymin,ymax)
                ax1.set_xlim(xmin,xmax)
                for ch,axis in self.plot_axes.items():
                    axis.set_ylim(*limits[ch])
            except ValueError as exc:
                if hasattr(self,'wave_info'):
                    self.wave_info.setText(f'Manual graph axes: {exc}')
        # mode == 1: ordinary Matplotlib fit-to-waveform data autoscaling.
        self.fig.tight_layout()
        self.canvas.draw_idle()

