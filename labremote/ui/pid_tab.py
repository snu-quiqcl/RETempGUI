"""MDT PID controls. The runner uses the same API as workflow files."""
import time
from collections import deque
from PyQt5 import QtCore,QtWidgets
from labremote.api.devices import device_api,Devices
from labremote.config.device_config import load_device_config


class PIDTab(QtWidgets.QWidget):
    def __init__(self,worker,bindings,parent=None):
        super().__init__(parent);self.worker=worker;self.bindings=bindings;self.api=device_api(worker)
        self.fields={};self.history=deque(maxlen=3000);self.last_sample=None;self.run_id=None
        root=QtWidgets.QVBoxLayout(self);form=QtWidgets.QGridLayout();root.addLayout(form)
        self.osa=QtWidgets.QComboBox();form.addWidget(QtWidgets.QLabel('OSA repeat source'),0,0);form.addWidget(self.osa,0,1)
        self.axis=QtWidgets.QComboBox();self.axis.addItems(['X','Y','Z']);form.addWidget(QtWidgets.QLabel('MDT axis'),0,2);form.addWidget(self.axis,0,3)
        defaults=load_device_config('mdt',getattr(parent,'name',None) or worker.name or 'mdt693b')['pid_defaults']
        specs=[('target_thz','Target (THz)',0,1000,9),('kp_v_per_ghz','Kp (V/GHz)',0,1e6,6),('ki_v_per_ghz_s','Ki (V/GHz/s)',0,1e6,6),('kd_v_s_per_ghz','Kd (V s/GHz)',0,1e6,6),('average_count','New traces per correction',1,100,0)]
        for row,(key,title,lo,hi,dec) in enumerate(specs,1):self.add_number(form,row,key,title,lo,hi,dec,defaults[key])
        self.use_fit=QtWidgets.QCheckBox('Use sech² spectral fit');root.addWidget(self.use_fit)
        toggle=QtWidgets.QCheckBox('Show PID limits / signal conditions');root.addWidget(toggle)
        advanced=QtWidgets.QWidget();limits=QtWidgets.QGridLayout(advanced);root.addWidget(advanced);advanced.hide();toggle.toggled.connect(advanced.setVisible)
        settings=[('min_v','Minimum voltage (V)',0,150),('max_v','Maximum voltage (V)',0,150),('max_step_v','Maximum step (V)',.000001,150),('max_slew_v_per_s','Maximum slew (V/s)',.000001,150),('capture_ghz','Capture range (GHz)',.000001,1e6),('deadband_ghz','Deadband (GHz)',.000001,1e6),('min_peak_dbm','Minimum peak (dBm)',-150,50),('minimum_snr_db','Minimum SNR (dB)',0,100),('derivative_filter_s','Derivative filter (s)',.001,1000),('max_gap_s','Maximum valid-trace gap (s)',.001,3600),('lease_s','GUI heartbeat timeout (s)',2,120)]
        for row,(key,title,lo,hi) in enumerate(settings):self.add_number(limits,row,key,title,lo,hi,6,defaults[key])
        self.polarity=QtWidgets.QComboBox();self.polarity.addItem('+1',1);self.polarity.addItem('-1',-1)
        limits.addWidget(QtWidgets.QLabel('Polarity'),len(settings),0);limits.addWidget(self.polarity,len(settings),1)
        row=QtWidgets.QHBoxLayout();root.addLayout(row)
        self.start_btn=QtWidgets.QPushButton('Start PID');self.stop_btn=QtWidgets.QPushButton('Stop PID / hold voltage');self.update_btn=QtWidgets.QPushButton('Apply target / gains')
        for b in (self.start_btn,self.stop_btn,self.update_btn):row.addWidget(b)
        self.start_btn.clicked.connect(self.start);self.stop_btn.clicked.connect(self.api.stop_pid);self.update_btn.clicked.connect(self.update_runtime)
        self.status=QtWidgets.QLabel('Start OSA Repeat first. PID uses only new completed traces.');self.status.setWordWrap(True);root.addWidget(self.status)
        self.values=QtWidgets.QLabel();self.values.setWordWrap(True);root.addWidget(self.values)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        self.figure=Figure(figsize=(8,3));self.canvas=FigureCanvasQTAgg(self.figure);root.addWidget(self.canvas)
        worker.task_progress.connect(self.progress);worker.task_changed.connect(lambda *_:self.controls())
        self.timer=QtCore.QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(1000);self.tick()

    def add_number(self,form,row,key,title,lo,hi,dec,value):
        editor=QtWidgets.QDoubleSpinBox();editor.setRange(lo,hi);editor.setDecimals(dec);editor.setValue(value)
        form.addWidget(QtWidgets.QLabel(title),row,0);form.addWidget(editor,row,1);self.fields[key]=editor

    def tick(self):
        self.worker.ui_heartbeat=time.monotonic()
        if not self.worker.pid_runner.running():
            selected=self.osa.currentText();names=[bridge.worker.name for family,bridge in self.bindings().values() if family=='osa']
            if names!=[self.osa.itemText(i) for i in range(self.osa.count())]:
                self.osa.clear();self.osa.addItems(names);self.osa.setCurrentText(selected)
        self.controls()

    def controls(self):
        running=self.worker.pid_runner.running()
        self.start_btn.setEnabled(self.worker.ps is not None and bool(self.osa.count()) and not running)
        self.stop_btn.setEnabled(running);self.update_btn.setEnabled(running)
        for key,field in self.fields.items():field.setEnabled(not running or key in ('target_thz','kp_v_per_ghz','ki_v_per_ghz_s','kd_v_s_per_ghz'))
        for field in (self.osa,self.axis,self.polarity,self.use_fit):field.setEnabled(not running)

    def start(self):
        try:
            settings={k:v.value() for k,v in self.fields.items()};settings['average_count']=int(settings['average_count'])
            settings.update(axis=self.axis.currentText(),use_fit=self.use_fit.isChecked(),polarity=self.polarity.currentData())
            osa=Devices(self.bindings()).osa(self.osa.currentText())
            self.api.start_pid(osa,settings);self.controls()
        except Exception as exc:self.status.setText(str(exc))

    def update_runtime(self):
        self.api.update_pid(**{k:self.fields[k].value() for k in ('target_thz','kp_v_per_ghz','ki_v_per_ghz_s','kd_v_s_per_ghz')})

    def progress(self,label,data):
        if label!='MDT_PID':return
        handle=self.worker.pid_runner.handle
        if handle is not None and self.run_id!=handle.request_id:self.run_id=handle.request_id;self.history.clear();self.last_sample=None
        self.status.setText(data.get('status',data.get('phase',''))+(' — '+data['error'] if data.get('error') else ''))
        self.values.setText(' | '.join(f'{key}: {data[key]}' for key in ('voltage_v','measured_thz','error_ghz','snr_db','batch_collected','batch_size') if key in data))
        sample=data.get('samples',0)
        if sample and sample!=self.last_sample:
            self.last_sample=sample;self.history.append((time.monotonic(),data['voltage_v'],data.get('error_ghz',0)))
            self.figure.clear();axis=self.figure.add_subplot(111);right=axis.twinx();t=[r[0]-self.history[0][0] for r in self.history]
            axis.plot(t,[r[1] for r in self.history],color='tab:blue');right.plot(t,[r[2] for r in self.history],color='tab:orange')
            axis.set_xlabel('Elapsed seconds');axis.set_ylabel('MDT voltage (V)');right.set_ylabel('Error (GHz)');self.figure.subplots_adjust(left=.12,right=.87,bottom=.2,top=.94);self.canvas.draw_idle()
        self.controls()
