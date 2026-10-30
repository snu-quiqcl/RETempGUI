"""Four scan runners share the FPGA operation FIFO only while measuring."""
from pathlib import Path
import numpy as np
from PyQt5 import QtCore,QtWidgets
from labremote.api.devices import device_api,Devices
from labremote.config.device_config import load_device_config
from labremote.devices.fpga.controller import INPUTS


class MotorScanTab(QtWidgets.QWidget):
    def __init__(self,worker,bindings,number,parent=None):
        super().__init__(parent);self.worker=worker;self.bindings=bindings;self.number=number;self.api=device_api(worker)
        self.run_id=None;self.data=None;self.fields={};self.latest_state={};self.z_values=[];self.fit_artists=[]
        self.defaults=[('EA_px','EA_py','EA_pz'),('EC_px','EC_py','EC_pz'),('EC_sx','EC_sy','EC_sz'),('EA_sx','EA_sy','EA_sz')][number-1]
        cfg=load_device_config('fpga',getattr(parent,'name',None) or worker.name or 'fpga_local')['scan_defaults']
        root=QtWidgets.QVBoxLayout(self);root.setContentsMargins(6,6,6,6);root.setSpacing(4)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        self.figure=Figure(figsize=(7,4),facecolor='#101a2b');self.canvas=FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumHeight(260);root.addWidget(self.canvas,1)
        plane_line=QtWidgets.QHBoxLayout();plane_line.setSpacing(6);root.addLayout(plane_line)
        self.view_plane=QtWidgets.QComboBox();self.view_plane.setMaximumWidth(140)
        self.follow_z=QtWidgets.QCheckBox('Follow current Z');self.follow_z.setChecked(True)
        plane_line.addWidget(QtWidgets.QLabel('View Z'));plane_line.addWidget(self.view_plane);plane_line.addWidget(self.follow_z)
        self.fit_label=QtWidgets.QLabel('MFD: fit after a completed scan');self.fit_label.setWordWrap(True)
        plane_line.addWidget(self.fit_label,1)
        self.view_plane.currentIndexChanged.connect(self.render_plane)
        self.status=QtWidgets.QLabel('Connect FPGA and two motors first.');self.status.setWordWrap(True);root.addWidget(self.status)

        self.settings_panel=QtWidgets.QWidget();settings=QtWidgets.QVBoxLayout(self.settings_panel)
        settings.setContentsMargins(0,0,0,0);settings.setSpacing(4);root.addWidget(self.settings_panel)
        form=QtWidgets.QGridLayout();form.setHorizontalSpacing(6);form.setVerticalSpacing(3);settings.addLayout(form)
        for column in range(2,6):form.setColumnStretch(column,1)
        self.x_motor=QtWidgets.QComboBox();self.y_motor=QtWidgets.QComboBox();self.z_motor=QtWidgets.QComboBox()
        self.z_enabled=QtWidgets.QCheckBox('Z scan');self.channel=QtWidgets.QComboBox()
        for box,default in zip((self.x_motor,self.y_motor,self.z_motor),self.defaults):
            box.setProperty('selected_motor',default)
            box.currentTextChanged.connect(lambda text,b=box:b.setProperty('selected_motor',text) if text else None)
        for n,(name,pin) in INPUTS.items():self.channel.addItem(name,n)
        self.channel.setCurrentIndex(number-1)
        for col,title in enumerate(('Axis','Motor','Start (µm)','End (µm)','Step (µm)','µm / server unit')):
            form.addWidget(QtWidgets.QLabel(title),0,col)
        for row,(axis,box) in enumerate(zip('xyz',(self.x_motor,self.y_motor,self.z_motor)),1):
            form.addWidget(self.z_enabled if axis=='z' else QtWidgets.QLabel(axis.upper()),row,0)
            form.addWidget(box,row,1)
            for col,(suffix,lo,hi) in enumerate((('start_um',0,12000),('stop_um',0,12000),('step_um',.001,12000),('um_per_unit',.001,1e9)),2):
                key=axis+'_'+suffix;editor=QtWidgets.QDoubleSpinBox();editor.setDecimals(3)
                editor.setRange(lo,hi);editor.setValue(cfg[key]);self.fields[key]=editor
                form.addWidget(editor,row,col)
        self.z_enabled.toggled.connect(self.controls)
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
        self.config_widgets=[self.x_motor,self.y_motor,self.z_motor,self.z_enabled,self.channel,self.directory,browse,*self.fields.values()]
        worker.task_progress.connect(self.progress);worker.task_changed.connect(self.changed)
        self.timer=QtCore.QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(1000);self.tick()

    def changed(self,label,handle):
        if label=='MOTOR_SCAN' and handle.arguments.get('scan')==self.number and handle.error is not None:self.status.setText(str(handle.error))
        self.controls()

    def browse(self):
        path=QtWidgets.QFileDialog.getExistingDirectory(self,'Scan save folder',self.directory.text())
        if path:self.directory.setText(path)

    def tick(self):
        if not self.worker.scan_runners[self.number].running():
            names=[bridge.worker.name for family,bridge in self.bindings().values() if family=='motors']
            for box,default in zip((self.x_motor,self.y_motor,self.z_motor),self.defaults):
                selected=box.property('selected_motor') or default
                if names!=[box.itemText(i) for i in range(box.count())]:
                    blocker=QtCore.QSignalBlocker(box)
                    box.clear();box.addItems(names);box.setCurrentIndex(box.findText(selected))
                    del blocker
        self.controls()

    def controls(self):
        running=self.worker.scan_runners[self.number].running()
        self.start_btn.setEnabled(not running and not self.worker.waveform_runner.running() and self.worker.ps is not None and bool(self.x_motor.currentText() and self.y_motor.currentText() and (not self.z_enabled.isChecked() or self.z_motor.currentText())))
        active=running and self.worker.scan_runners[self.number].settings.get('scan')==self.number
        self.stop_btn.setEnabled(active)
        for field in self.config_widgets:field.setEnabled(not active)
        self.z_motor.setEnabled(not active and self.z_enabled.isChecked())
        for key in ('z_start_um','z_stop_um','z_step_um','z_um_per_unit'):self.fields[key].setEnabled(not active and self.z_enabled.isChecked())

    def request(self):
        devices=Devices(self.bindings());x=devices.motor(self.x_motor.currentText());y=devices.motor(self.y_motor.currentText())
        settings={k:v.value() for k,v in self.fields.items()};settings['average']=int(settings['average'])
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
            blocker=QtCore.QSignalBlocker(self.view_plane);self.view_plane.clear()
            self.view_plane.addItems([f'{value:g} µm' for value in self.z_values] or ['XY'])
            self.view_plane.setCurrentIndex(0);del blocker
            self.view_plane.setEnabled(bool(self.z_values));self.follow_z.setEnabled(bool(self.z_values))
            self.figure.clear();self.axes=self.figure.add_subplot(111);self.fit_artists=[]
            self.axes.set_facecolor('#101a2b');self.axes.tick_params(colors='#dce5f4')
            dx=xs[1]-xs[0];dy=ys[1]-ys[0]
            blank=self.data[0] if self.z_values else self.data
            self.image=self.axes.imshow(np.ma.masked_invalid(blank),origin='lower',aspect='equal',extent=[xs[0]-dx/2,xs[-1]+dx/2,ys[0]-dy/2,ys[-1]+dy/2])
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
        self.canvas.draw_idle()
