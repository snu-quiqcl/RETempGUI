"""Four scan runners share the FPGA operation FIFO only while measuring."""
from pathlib import Path
import json
import math
import time
import numpy as np
from labremote.runtime.parameters import LIBRARY
from PyQt5 import QtCore,QtWidgets
from labremote.api.devices import device_api,Devices
from labremote.config.device_config import load_device_config
from labremote.devices.fpga.controller import INPUTS


from labremote.config.roles import scan_roles
SCAN_ROLES = scan_roles()
SCAN_TABS = tuple((r['title'],tuple(r['axes'])) for r in SCAN_ROLES)


class MotorScanTab(QtWidgets.QWidget):
    def __init__(self,worker,bindings,number,parent=None):
        super().__init__(parent);self.worker=worker;self.bindings=bindings;self.number=number;self.api=device_api(worker)
        self.run_id=None;self.data=None;self.fields={};self.latest_state={};self.z_values=[];self.fit_artists=[]
        self.title,self.defaults=SCAN_TABS[number-1]
        self.position_labels={};self.manual_move=None
        self.zoom_selector=None
        cfg=load_device_config('fpga',getattr(parent,'name',None) or worker.name or 'fpga_local')['scan_defaults']
        self.scales={axis+'_um_per_unit':cfg[axis+'_um_per_unit'] for axis in 'xyz'}
        root=QtWidgets.QVBoxLayout(self);root.setContentsMargins(6,6,6,6);root.setSpacing(4)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        self.figure=Figure(figsize=(7,4),facecolor='#101a2b');self.canvas=FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumHeight(340);root.addWidget(self.canvas,1)
        self.mfd_figure=Figure(figsize=(7,2),facecolor='#101a2b');self.mfd_canvas=FigureCanvasQTAgg(self.mfd_figure)
        self.mfd_canvas.setMinimumHeight(110);self.mfd_canvas.setMaximumHeight(130)
        self.mfd_axes=self.mfd_figure.add_subplot(111);self.mfd_axes.set_facecolor('#101a2b')
        self.mfd_axes.set_xlabel('Z position (µm)',color='#dce5f4');self.mfd_axes.set_ylabel('MFD (µm)',color='#dce5f4')
        self.mfd_axes.tick_params(colors='#dce5f4');self.mfd_axes.grid(alpha=.2)
        self.mfd_lines=[self.mfd_axes.plot([],[],style,label=label)[0] for style,label in [('o-','MFD X'),('s-','MFD Y')]]
        self.mfd_axes.legend();self.mfd_figure.subplots_adjust(left=.12,right=.97,bottom=.36,top=.9)
        root.addWidget(self.mfd_canvas);self.mfd_canvas.hide()
        plane_line=QtWidgets.QHBoxLayout();plane_line.setSpacing(6);root.addLayout(plane_line)
        self.view_plane=QtWidgets.QComboBox();self.view_plane.setMaximumWidth(140)
        self.follow_z=QtWidgets.QCheckBox('Follow current Z');self.follow_z.setChecked(True)
        plane_line.addWidget(QtWidgets.QLabel('View Z'));plane_line.addWidget(self.view_plane);plane_line.addWidget(self.follow_z)
        self.fit_label=QtWidgets.QLabel('MFD: fit after a completed scan');self.fit_label.setWordWrap(True)
        plane_line.addWidget(self.fit_label,1)
        self.reset_zoom_btn=QtWidgets.QPushButton('Reset XY zoom');plane_line.addWidget(self.reset_zoom_btn)
        self.reset_zoom_btn.clicked.connect(self.reset_xy_zoom)
        self.canvas.setToolTip('Left-drag to zoom XY; Reset XY zoom restores the full scan')
        self.view_plane.currentIndexChanged.connect(self.render_plane)
        self.status=QtWidgets.QLabel('Connect FPGA and two motors first.');self.status.setWordWrap(True);root.addWidget(self.status)

        self.settings_panel=QtWidgets.QWidget();settings=QtWidgets.QVBoxLayout(self.settings_panel)
        settings.setContentsMargins(0,0,0,0);settings.setSpacing(4);root.addWidget(self.settings_panel)
        form=QtWidgets.QGridLayout();form.setHorizontalSpacing(6);form.setVerticalSpacing(3);settings.addLayout(form)
        for column in range(2,6):form.setColumnStretch(column,1)
        self.x_motor=QtWidgets.QComboBox();self.y_motor=QtWidgets.QComboBox();self.z_motor=QtWidgets.QComboBox()
        self.z_enabled=QtWidgets.QCheckBox('Z scan');self.channel=QtWidgets.QComboBox()
        for box,default in zip((self.x_motor,self.y_motor,self.z_motor),self.defaults):
            box.addItem(default);box.setEnabled(False)
        for n,(name,pin) in INPUTS.items():self.channel.addItem(name,n)
        self.channel.setCurrentIndex(SCAN_ROLES[number-1]['pmt_index'])
        for col,title in enumerate(('Axis','Motor','Start (µm)','End (µm)','Step (µm)','Current (µm)')):
            form.addWidget(QtWidgets.QLabel(title),0,col)
        for row,(axis,box) in enumerate(zip('xyz',(self.x_motor,self.y_motor,self.z_motor)),1):
            form.addWidget(self.z_enabled if axis=='z' else QtWidgets.QLabel(axis.upper()),row,0)
            form.addWidget(box,row,1)
            for col,(suffix,lo,hi) in enumerate((('start_um',0,12000),('stop_um',0,12000),('step_um',.001,12000)),2):
                key=axis+'_'+suffix;editor=QtWidgets.QDoubleSpinBox();editor.setDecimals(3)
                editor.setRange(lo,hi);editor.setValue(cfg[key]);self.fields[key]=editor
                form.addWidget(editor,row,col)
            self.position_labels[axis]=QtWidgets.QLabel('Disconnected');form.addWidget(self.position_labels[axis],row,5)
        for axis in 'xyz':
            self.fields[axis+'_step_um'].valueChanged.connect(lambda value,a=axis:self.step_changed(a,value))
            self.step_changed(axis,self.fields[axis+'_step_um'].value())
        self.z_enabled.toggled.connect(self.controls)
        manual=QtWidgets.QHBoxLayout();settings.addLayout(manual)
        manual.addWidget(QtWidgets.QLabel('Z absolute target (µm)'))
        self.z_target=QtWidgets.QDoubleSpinBox();self.z_target.setDecimals(3);self.z_target.setRange(0,12000)
        manual.addWidget(self.z_target);self.move_z_btn=QtWidgets.QPushButton('Move Z');manual.addWidget(self.move_z_btn)
        self.move_z_btn.clicked.connect(self.move_z)
        self.load_btn=QtWidgets.QPushButton('Load scan setting');manual.addWidget(self.load_btn)
        self.load_btn.clicked.connect(self.load_scan_setting)
        acquisition=QtWidgets.QHBoxLayout();acquisition.setSpacing(6);settings.addLayout(acquisition)
        acquisition.addWidget(QtWidgets.QLabel('PMT'));acquisition.addWidget(self.channel)
        for key,title,lo,hi,dec in [('exposure_ms','Exposure (ms)',.1,6000,1),('average','Average',1,100000,0),('settle_ms','Settle (ms)',0,60000,0)]:
            editor=QtWidgets.QDoubleSpinBox();editor.setDecimals(dec);editor.setRange(lo,hi);editor.setValue(cfg[key]);self.fields[key]=editor
            acquisition.addWidget(QtWidgets.QLabel(title));acquisition.addWidget(editor)
        line=QtWidgets.QHBoxLayout();line.setSpacing(6);settings.addLayout(line)
        self.directory=QtWidgets.QLineEdit(cfg['directory']);line.addWidget(self.directory,1)
        browse=QtWidgets.QPushButton('Save folder');line.addWidget(browse);browse.clicked.connect(self.browse)
        self.start_btn=QtWidgets.QPushButton('Start scan');self.stop_btn=QtWidgets.QPushButton('Stop / save partial')
        line.addWidget(self.start_btn);line.addWidget(self.stop_btn)
        self.start_btn.clicked.connect(self.start);self.stop_btn.clicked.connect(lambda:self.api.stop_scan(self.number))
        note=QtWidgets.QLabel('Absolute coordinates · 1000 µm = 1 mm · X ascends each row · No automatic return')
        settings.addWidget(note)
        self.config_widgets=[self.load_btn,self.z_enabled,self.channel,self.directory,browse,*self.fields.values()]
        worker.task_progress.connect(self.progress);worker.task_changed.connect(self.changed)
        self.timer=QtCore.QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(1000);self.tick()

    def step_changed(self,axis,value):
        for suffix in ('start_um','stop_um'):
            self.fields[axis+'_'+suffix].setSingleStep(value)

    def changed(self,label,handle):
        if label=='MOTOR_SCAN' and handle.arguments.get('scan')==self.number and handle.error is not None:self.status.setText(str(handle.error))
        self.controls()

    def browse(self):
        path=QtWidgets.QFileDialog.getExistingDirectory(self,'Scan save folder',self.directory.text())
        if path:self.directory.setText(path)

    def motor_api(self,axis):
        try:return Devices(self.bindings()).motor(self.defaults['xyz'.index(axis)])
        except KeyError:return None

    @staticmethod
    def available(api):
        return api is not None and api.worker.ps is not None and not api.worker.connection_error and not api.worker._closing

    @staticmethod
    def reserved(api):
        return any(task.running() for task in tuple(api.worker._background_tasks))

    def tick(self):
        for axis,label in self.position_labels.items():
            api=self.motor_api(axis)
            if not self.available(api):label.setText('Disconnected');continue
            state=LIBRARY.read((api.worker._execution_device,'status'))
            value=state.observed if state.quality=='valid' else None
            position=value.get('position') if isinstance(value,dict) and value.get('online') is not False else None
            if isinstance(position,(int,float)) and not isinstance(position,bool) and math.isfinite(position):
                age=time.monotonic()-state.observed_at
                label.setText(f"{position*self.scales[axis+'_um_per_unit']:.3f}"+(' (last)' if age>3 else ''))
                label.setToolTip(f'Last readback: {age:.1f} s ago')
            else:label.setText('Unavailable')
            # Reuse scan move readbacks; never inject polling into an active scan.
            if self.isVisible() and not self.reserved(api) and not api.worker.has_requests():
                api.status()
        if self.manual_move is not None and self.manual_move.done.is_set():
            self.status.setText(str(self.manual_move.error) if self.manual_move.error else 'Z move completed')
            self.manual_move=None
        self.controls()

    def controls(self):
        running=self.worker.scan_runners[self.number].running()
        motors=[self.motor_api(a) for a in ('xyz' if self.z_enabled.isChecked() else 'xy')]
        moving=self.manual_move is not None and not self.manual_move.done.is_set()
        ready=all(self.available(api) and not self.reserved(api) for api in motors)
        self.start_btn.setEnabled(not running and not moving and ready and not self.worker.waveform_runner.running() and self.worker.ps is not None)
        self.stop_btn.setEnabled(running)
        for field in self.config_widgets:field.setEnabled(not running)
        for key in ('z_start_um','z_stop_um','z_step_um'):self.fields[key].setEnabled(not running and self.z_enabled.isChecked())
        z=self.motor_api('z')
        # A periodic STATUS request must not lock manual movement: MOVE queues behind it.
        can_move=not running and not moving and self.available(z) and not self.reserved(z)
        self.z_target.setEnabled(not running and not moving);self.move_z_btn.setEnabled(can_move)

    def move_z(self):
        try:
            api=self.motor_api('z')
            if not self.available(api) or self.reserved(api) or self.worker.scan_runners[self.number].running():
                raise RuntimeError('Connect Z motor and stop its scan before moving')
            if self.manual_move is not None and not self.manual_move.done.is_set():return
            target=self.z_target.value()/self.scales['z_um_per_unit']
            def move(worker):
                # Recheck at execution, in case a workflow claimed the motor after the click.
                if self.reserved(api):raise RuntimeError('Z motor belongs to an active workflow')
                from labremote.operation.motors.move import move
                return move(worker.ps,target)
            self.manual_move=api._submit('MOVE',move)
            self.status.setText('Moving Z…');self.controls()
        except Exception as exc:self.status.setText(str(exc))

    def load_scan_setting(self):
        base=Path(self.directory.text()).expanduser()
        if not base.is_absolute():base=Path(__file__).resolve().parents[2]/base
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Load scan setting',str(base),
            'Scan settings (configuration.json result.json);;JSON files (*.json)')
        if path:self.load_scan_file(path)

    def load_scan_file(self,path):
        try:
            if self.worker.scan_runners[self.number].running():raise ValueError('Stop scan before loading settings')
            payload=json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if not isinstance(payload,dict):raise ValueError('Expected a scan configuration object')
            values=payload.get('configuration',payload)
            if not isinstance(values,dict):raise ValueError('Invalid scan configuration')
            z=values.get('z_motor')
            if (values.get('x_motor'),values.get('y_motor'))!=self.defaults[:2] or z not in (None,self.defaults[2]):
                raise ValueError('Scan motor names do not match this tab: '+', '.join(self.defaults))
            for key,widget in self.fields.items():
                value=values[key]
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not widget.minimum()<=value<=widget.maximum():
                    raise ValueError('Invalid saved '+key)
            if values['average']!=int(values['average']):raise ValueError('Average must be an integer')
            if type(values['pmt']) is not int:raise ValueError('Invalid saved PMT')
            index=self.channel.findData(values['pmt'])
            if index<0:raise ValueError('Invalid saved PMT')
            from labremote.devices.fpga.scan_model import axis_points
            for axis in ('xyz' if z else 'xy'):
                axis_points(*(values[axis+'_'+key] for key in ('start_um','stop_um','step_um')))
            # Validate everything before changing fields. Keep this PC's save folder and calibration.
            for key,widget in self.fields.items():widget.setValue(values[key])
            self.z_enabled.setChecked(z is not None);self.channel.setCurrentIndex(index)
            self.status.setText('Scan settings loaded: '+str(path));self.controls()
        except Exception as exc:self.status.setText('Cannot load scan settings: '+str(exc))

    def zoom_xy(self,press,release):
        if self.data is None or any(v is None for v in (press.xdata,press.ydata,release.xdata,release.ydata)):return
        left,right,bottom,top=self.image.get_extent()
        x0,x1=sorted((press.xdata,release.xdata));y0,y1=sorted((press.ydata,release.ydata))
        x0,x1=max(left,x0),min(right,x1);y0,y1=max(bottom,y0),min(top,y1)
        if x0>=x1 or y0>=y1:return
        self.axes.set_xlim(x0,x1);self.axes.set_ylim(y0,y1);self.canvas.draw_idle()

    def reset_xy_zoom(self):
        if self.data is None:return
        left,right,bottom,top=self.image.get_extent()
        self.axes.set_xlim(left,right);self.axes.set_ylim(bottom,top);self.canvas.draw_idle()

    def request(self):
        devices=Devices(self.bindings());x=devices.motor(self.x_motor.currentText());y=devices.motor(self.y_motor.currentText())
        settings={**self.scales,**{k:v.value() for k,v in self.fields.items()}};settings['average']=int(settings['average'])
        settings.update(pmt=self.channel.currentData(),directory=self.directory.text(),scan=self.number)
        z=devices.motor(self.z_motor.currentText()) if self.z_enabled.isChecked() else None
        return x,y,settings,z

    def start(self):
        try:
            x,y,settings,z=self.request()
            self.api.start_scan(x,y,settings,z_motor=z);self.controls()
        except Exception as exc:self.status.setText(str(exc))

    def progress(self,label,state):
        if label!='MOTOR_SCAN' or state.get('scan')!=self.number:return
        runner=self.worker.scan_runners[self.number]
        run_id=state.get('run_id')
        if runner.handle is None or run_id!=runner.handle.request_id:return
        self.latest_state=state
        if self.run_id!=run_id and 'xs' in state:
            self.run_id=run_id;xs=state['xs'];ys=state['ys'];self.z_values=state.get('zs',[])
            shape=(len(self.z_values),len(ys),len(xs)) if self.z_values else (len(ys),len(xs))
            self.data=np.full(shape,np.nan)
            self.mfd_canvas.setVisible(bool(self.z_values))
            blocker=QtCore.QSignalBlocker(self.view_plane);self.view_plane.clear()
            self.view_plane.addItems([f'{value:g} µm' for value in self.z_values] or ['XY'])
            self.view_plane.setCurrentIndex(0);del blocker
            self.view_plane.setEnabled(bool(self.z_values));self.follow_z.setEnabled(bool(self.z_values))
            if self.zoom_selector is not None:self.zoom_selector.disconnect_events()
            self.figure.clear();self.axes=self.figure.add_subplot(111);self.fit_artists=[]
            self.axes.set_facecolor('#101a2b');self.axes.tick_params(colors='#dce5f4')
            dx=xs[1]-xs[0];dy=ys[1]-ys[0]
            blank=self.data[0] if self.z_values else self.data
            self.image=self.axes.imshow(np.ma.masked_invalid(blank),origin='lower',aspect='equal',extent=[xs[0]-dx/2,xs[-1]+dx/2,ys[0]-dy/2,ys[-1]+dy/2])
            from matplotlib.widgets import RectangleSelector
            self.zoom_selector=RectangleSelector(self.axes,self.zoom_xy,useblit=False,button=[1],minspanx=5,minspany=5,spancoords='pixels',interactive=False)
            colorbar=self.figure.colorbar(self.image,ax=self.axes);colorbar.set_label('PMT counts (mean)',color='#dce5f4');colorbar.ax.tick_params(colors='#dce5f4')
            self.axes.set_xlabel('X position (um)',color='#dce5f4');self.axes.set_ylabel('Y position (um)',color='#dce5f4');self.figure.subplots_adjust(left=.10,right=.88,bottom=.12,top=.94)
        if self.data is not None and state.get('point') is not None:
            ix,iy,value=state['point'];iz=state.get('iz',0)
            plane=self.data[iz] if self.z_values else self.data;plane[iy,ix]=value
        if self.z_values and self.follow_z.isChecked():self.view_plane.setCurrentIndex(state.get('iz',0))
        summary=f"{state.get('status',state.get('phase',''))}: {state.get('points',0)}/{state.get('total','?')}"
        self.status.setText(' · '.join(str(v) for v in (summary,state.get('error'),state.get('folder')) if v))
        self.status.setToolTip(str(state.get('folder','')))
        self.render_plane();self.controls()

    def render_plane(self,*args):
        if self.data is None:return
        index=max(0,self.view_plane.currentIndex())
        plane=self.data[index] if self.z_values else self.data
        self.image.set_data(np.ma.masked_invalid(plane));valid=plane[np.isfinite(plane)]
        if valid.size:self.image.set_clim(float(valid.min()),max(float(valid.min())+1,float(valid.max())))
        self.axes.set_title(f'Z = {self.z_values[index]:g} µm' if self.z_values else 'XY scan',color='#dce5f4')
        for artist in self.fit_artists:artist.remove()
        self.fit_artists=[]
        state=self.latest_state;planes=state.get('z_fits',[])
        fit=planes[index]['fit'] if self.z_values and index<len(planes) else state.get('fit') if not self.z_values else None
        lines=[]
        if fit:
            from matplotlib.patches import Ellipse
            if 'error' in fit:lines.append('Elliptical fit unavailable: '+fit['error'])
            else:
                lines.append(f"Elliptical MFD: X={fit['coupling_mfd_x_um']:.3f} µm, Y={fit['coupling_mfd_y_um']:.3f} µm; R²={fit['r_squared']:.4f}")
                artist=Ellipse((fit['x0_um'],fit['y0_um']),fit['coupling_mfd_x_um'],fit['coupling_mfd_y_um'],fill=False,edgecolor='white')
                self.axes.add_patch(artist);self.fit_artists.append(artist);lines.extend(fit['warnings'])
        self.fit_label.setText('\n'.join(lines) if lines else 'Partial scan: fit skipped' if state.get('status') in ('failed','cancelled') else 'MFD: measuring')
        self.render_mfd()
        self.canvas.draw_idle()

    def render_mfd(self):
        if not self.z_values:return
        fits={entry['iz']:entry['fit'] for entry in self.latest_state.get('z_fits',[])}
        for line,key in zip(self.mfd_lines,('coupling_mfd_x_um','coupling_mfd_y_um')):
            values=[fits.get(i,{}).get(key,np.nan) for i in range(len(self.z_values))]
            line.set_data(self.z_values,values)
        self.mfd_axes.relim();self.mfd_axes.autoscale_view();self.mfd_canvas.draw_idle()
