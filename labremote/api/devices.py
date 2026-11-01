"""The same nonblocking API for UI and workflow callers."""
from labremote.runtime.jobs import ExecutionHandle
from labremote.runtime.io import Context, acquire
from labremote.operation import windfreak
from labremote.config.ramp import PowerConfig
from labremote.operation.windfreak.set_power import set_power
from labremote.config.device_config import load_rf_device_config

SUPPORTED_FAMILIES = frozenset({'windfreak', 'sg384', 'anapico', 'dds4', 'ds1052e', 'mso7054', 'thermotek', 'keithley', 'osa', 'mdt', 'fpga', 'motors', 'ccd'})

class DeviceAPI:
    def __init__(self, worker, channel=None, group=None):
        self.worker, self.channel, self.group = worker, channel, group

    def _submit(self, label, callback, *, arguments=None, write_guard=None):
        handle = ExecutionHandle(label, callback, self.group)
        handle.arguments = dict(arguments or {})
        if getattr(self.group,'scan_number',None) is not None:
            handle.arguments.update(scan=self.group.scan_number,scan_run_id=self.group.task_run_id)
        handle.write_guard = write_guard
        from labremote.runtime.runner import OperationRunner
        OperationRunner.submit(self.worker, handle)
        return handle

    def connect(self, host, port, name):
        return self._submit('CONNECT', lambda w: w.connect_device(host, port, name))

    def disconnect(self):
        self.worker.cancel_pending()
        return self._submit('DISCONNECT', lambda w: w.disconnect_device())

    def acquire(self, path):
        def read(w):
            if not isinstance(path, str) or any(not p.isidentifier() or p.startswith('_') for p in path.split('.')):
                raise ValueError('Invalid parameter path')
            target = w.ps
            for part in path.split('.'): target = getattr(target, part)
            return acquire(target)
        return self._submit('ACQUIRE ' + str(path), read)

    def refresh(self):
        return self._submit('REFRESH', lambda w: w.refresh())

    def auto_monitor(self):
        from labremote.runtime.auto_monitor import AUTO_MONITOR
        AUTO_MONITOR.request(self.worker)

    def monitor(self):
        from labremote.runtime.jobs import aggregate_handles
        if self.worker.connection_error or self.worker.ps is None:
            def unavailable(w): raise ConnectionError('Device connection unavailable; connect explicitly')
            return self._submit('MONITOR', unavailable)
        try:
            children = self.worker.scan_monitor(group=self.group)
        except Exception as error:
            def failed_scan(w, error=error): raise error
            return self._submit('MONITOR', failed_scan)
        return aggregate_handles('MONITOR', children, self.group)

    def submit(self, action, *args):
        common = {'CONNECT': self.connect, 'DISCONNECT': self.disconnect,
                  'REFRESH': self.refresh, 'MONITOR': self.monitor, 'ACQUIRE': self.acquire}
        return common[action](*args)

    def cancel(self):
        self.worker.cancel_backgrounds()
        self.worker.cancel_power_ramp()


class WindfreakAPI(DeviceAPI):
    def _channel(self, w):
        if self.channel not in ('A', 'B'): raise ValueError('Select Windfreak channel A or B')
        return getattr(w.ps, 'channel_' + self.channel)

    def set_frequency(self, hz):
        return self._submit('SET', lambda w: windfreak.set_frequency(w.ps, self.channel, hz))

    def set_phase(self, degrees):
        return self._submit('SET', lambda w: windfreak.set_phase(w.ps, self.channel, degrees))

    def set_output(self, enabled):
        def execute(w):
            ch = self._channel(w)
            cfg = load_rf_device_config('windfreak', w.name)['rf_operation']
            config = PowerConfig(cfg['low_power_dbm'], cfg['max_step_vpp'], cfg['interval_s'])
            if enabled is True: windfreak.windfreak_on(Context(), ch.power_dbm, ch.output_enabled, config)
            elif enabled is False: windfreak.windfreak_off(Context(), ch.power_dbm, ch.output_enabled, config)
            else: Context().assign(ch.output_enabled, enabled)
        return self._submit('OUTPUT', execute)

    def on(self): return self.set_output(True)
    def off(self): return self.set_output(False)

    def set_power(self, target_dbm, *, interval_s=None):
        def execute(w):
            ch = self._channel(w)
            cfg = load_rf_device_config('windfreak', w.name)['rf_operation']
            set_power(power=ch.power_dbm, target_dbm=target_dbm,
                      config=PowerConfig(cfg['low_power_dbm'], cfg['max_step_vpp'],
                                         cfg['interval_s'] if interval_s is None else interval_s))
        return self._submit('SET_POWER', execute, arguments=dict(target_dbm=target_dbm,
            interval_s=interval_s, channel=self.channel))

    def set_external_reference(self, hz):
        return self._submit('EXTERNAL_REFERENCE', lambda w: windfreak.configure_external_reference(w.ps, hz))

    def set_internal_reference(self, mode='internal 10mhz'):
        operations = {'internal 10mhz': windfreak.set_internal_reference_10mhz,
                      'internal 27mhz': windfreak.set_internal_reference_27mhz}
        return self._submit('INTERNAL_REFERENCE', lambda w: operations[mode](w.ps))

    def submit(self, action, *args):
        if action == 'CONNECT': return self.connect(*args)
        if action == 'DISCONNECT': return self.disconnect()
        if action == 'REFRESH': return self.refresh()
        if action == 'MONITOR': return self.monitor()
        if action == 'SET':
            key, ch, value = args
            api = WindfreakAPI(self.worker, ch, self.group)
            return {'frequency_hz': api.set_frequency, 'phase_deg': api.set_phase}[key](value)
        if action == 'OUTPUT': return WindfreakAPI(self.worker, args[0], self.group).set_output(args[1])
        if action == 'EXTERNAL_REFERENCE': return self.set_external_reference(*args)
        if action == 'INTERNAL_REFERENCE': return self.set_internal_reference(*args)
        raise ValueError('Unknown operation: ' + action)

class Devices:
    def __init__(self, bindings, *, group=None):
        self.group = group
        self._workers = {}
        for family, bridge in bindings.values():
            if family not in SUPPORTED_FAMILIES: continue
            key = (family, bridge.worker.name)
            if key in self._workers and self._workers[key] is not bridge.worker:
                raise ValueError('Ambiguous device name: ' + key[1])
            self._workers[key] = bridge.worker

    def names(self): return tuple(name for family,name in self._workers)

    def windfreak(self, name, *, channel):
        return WindfreakAPI(self._workers['windfreak',name], channel, self.group)

    def sg384(self, name, *, port='N'):
        return SG384API(self._workers['sg384',name], port, self.group)

    def anapico(self, name):
        return AnaPicoAPI(self._workers['anapico',name], group=self.group)

    def dds(self, name, *, channel):
        return DDS4API(self._workers['dds4',name], channel, self.group)

    def ds1052e(self, name):
        return DS1052EAPI(self._workers['ds1052e',name],group=self.group)

    def mso7054(self, name):
        return MSO7054API(self._workers['mso7054',name],group=self.group)

    def thermotek(self, name='t257p'):
        return ThermotekAPI(self._workers['thermotek',name],group=self.group)

    def keithley(self, name='keithley_ps', *, channel=1):
        return KeithleyAPI(self._workers['keithley',name],channel,group=self.group)

    def osa(self, name='aq6373'):
        return OSAAPI(self._workers['osa',name],group=self.group)

    def mdt(self, name='mdt693b'):
        return MDTAPI(self._workers['mdt',name],group=self.group)

    def fpga(self, name='fpga_local'):
        return FPGAAPI(self._workers['fpga',name],group=self.group)

    def ccd(self, name='ccd_local'):
        from labremote.devices.ccd.worker import CCDAPI
        return CCDAPI(self._workers['ccd', name], group=self.group)

    def motor(self, name):
        return MotorAPI(self._workers['motors',name],group=self.group)

    def dds4(self, name, *, channel):
        return self.dds(name, channel=channel)

    def wait(self, seconds):
        import math
        from labremote.runtime.errors import OperationCancelled
        if not math.isfinite(seconds) or seconds < 0: raise ValueError('Invalid wait interval')
        if self.group.stop.wait(seconds): raise OperationCancelled('Workflow cancelled during wait')


def device_api(worker, family=None, *, channel=None, group=None):
    family = family or worker.family
    if family == 'ccd':
        from labremote.devices.ccd.worker import CCDAPI
        return CCDAPI(worker, channel, group)
    return {'windfreak':WindfreakAPI,'sg384':SG384API,'anapico':AnaPicoAPI,'dds4':DDS4API,'ds1052e':DS1052EAPI,
            'mso7054':MSO7054API,'thermotek':ThermotekAPI,'keithley':KeithleyAPI,'osa':OSAAPI,'mdt':MDTAPI,'fpga':FPGAAPI,'motors':MotorAPI}[family](worker, channel, group)


class SG384API(DeviceAPI):
    def _power(self, w):
        if self.channel not in ('BNC','N'): raise ValueError('Select SG384 port BNC or N')
        return getattr(w.ps, self.channel.lower()+'_power_dbm')

    def _config(self, w, interval_s=None):
        cfg=load_rf_device_config('sg384',w.name)['rf_operation']
        return PowerConfig(cfg['low_power_dbm'][self.channel],cfg['max_step_vpp'],
                           cfg['interval_s'] if interval_s is None else interval_s)

    def set_frequency(self, hz):
        from labremote.operation.sg384.set_frequency import set_frequency
        return self._submit('SET_FREQUENCY',lambda w:set_frequency(w.ps,hz))

    def set_phase(self, degrees):
        from labremote.operation.sg384.set_phase import set_phase
        return self._submit('SET_PHASE',lambda w:set_phase(w.ps,degrees))

    def set_power(self, target_dbm, *, unit='dBm', interval_s=None):
        from labremote.operation.sg384.set_power import set_power
        return self._submit('SET_POWER',lambda w:set_power(power=self._power(w),target_dbm=target_dbm,
            unit=unit,config=self._config(w,interval_s)),arguments=dict(port=self.channel,target=target_dbm,unit=unit))

    def on(self):
        from labremote.operation.sg384.sg384_on import sg384_on
        def execute(w):
            power=self._power(w)
            return sg384_on(Context(),power,getattr(w.ps,self.channel.lower()+'_output'),self._config(w))
        return self._submit('OUTPUT',execute)

    def off(self):
        from labremote.operation.sg384.sg384_off import sg384_off
        def execute(w):
            power=self._power(w)
            return sg384_off(Context(),power,getattr(w.ps,self.channel.lower()+'_output'),self._config(w))
        return self._submit('OUTPUT',execute)

    def read_reference_events(self):
        from labremote.operation.sg384.read_reference_events import read_reference_events
        return self._submit('REFERENCE_EVENTS',lambda w:read_reference_events(w.ps))


class AnaPicoAPI(DeviceAPI):
    def set_frequency(self, hz):
        from labremote.operation.anapico.set_frequency import set_frequency
        return self._submit('SET_FREQUENCY',lambda w:set_frequency(w.ps,hz))

    def set_phase(self, degrees):
        from labremote.operation.anapico.set_phase import set_phase
        return self._submit('SET_PHASE',lambda w:set_phase(w.ps,degrees))

    def on(self):
        from labremote.operation.anapico.anapico_on import anapico_on
        return self._submit('OUTPUT',lambda w:anapico_on(w.ps))

    def off(self):
        from labremote.operation.anapico.anapico_off import anapico_off
        return self._submit('OUTPUT',lambda w:anapico_off(w.ps))

    def set_external_reference(self, hz):
        from labremote.operation.anapico.configure_external_reference import configure_external_reference
        return self._submit('EXTERNAL_REFERENCE',lambda w:configure_external_reference(w.ps,hz))

    def set_internal_reference(self):
        from labremote.operation.anapico.set_internal_reference import set_internal_reference
        return self._submit('INTERNAL_REFERENCE',lambda w:set_internal_reference(w.ps))

    def set_reference_output(self, hz, enabled):
        from labremote.operation.anapico.set_reference_output import set_reference_output
        return self._submit('REFERENCE_OUTPUT',lambda w:set_reference_output(w.ps,hz,enabled))


class DDS4API(DeviceAPI):
    def _channel(self, w):
        if type(self.channel) is not int or self.channel not in range(1,5):
            raise ValueError('Select DDS channel 1..4')
        return self.channel

    def set_frequency(self, hz):
        from labremote.operation.dds4.set_frequency import set_frequency
        return self._submit('SET_FREQUENCY',lambda w:set_frequency(w.ps,self._channel(w),hz))

    def set_phase(self, degrees):
        from labremote.operation.dds4.set_phase import set_phase
        return self._submit('SET_PHASE',lambda w:set_phase(w.ps,self._channel(w),degrees))

    def set_vva(self, level):
        from labremote.operation.dds4.set_vva import set_vva
        return self._submit('SET_VVA',lambda w:set_vva(w.ps,self._channel(w),level))

    def on(self):
        from labremote.operation.dds4.dds_on import dds_on
        return self._submit('OUTPUT',lambda w:dds_on(w.ps,self._channel(w)))

    def off(self):
        from labremote.operation.dds4.dds_off import dds_off
        return self._submit('OUTPUT',lambda w:dds_off(w.ps,self._channel(w)))

    def all_off(self):
        from labremote.operation.dds4.all_off import all_off
        return self._submit('ALL_OFF',lambda w:all_off(w.ps))


class DS1052EAPI(DeviceAPI):
    def start_waveform(self,channels=('CH1','CH2'),*,interval_s=1.0):
        return self.worker.waveform_runner.start(channels,interval_s,self.group)

    def stop_waveform(self):
        return self.worker.waveform_runner.cancel()

    def cancel(self):
        if self.worker.waveform_runner.running():return self.stop_waveform()
        return super().cancel()

    def configure_horizontal(self, time_scale_s, time_offset_s):
        from labremote.operation.ds1052e.configure_horizontal import configure_horizontal
        return self._submit('HORIZONTAL',lambda w:configure_horizontal(w.ps,time_scale_s,time_offset_s))

    def configure_vertical(self, channel, scale_vdiv, offset_v):
        from labremote.operation.ds1052e.configure_vertical import configure_vertical
        return self._submit('VERTICAL',lambda w:configure_vertical(w.ps,channel,scale_vdiv,offset_v))

    def configure_trigger(self, channel, level_v, *, slope='POS', sweep='AUTO'):
        from labremote.operation.ds1052e.configure_trigger import configure_trigger
        return self._submit('TRIGGER',lambda w:configure_trigger(w.ps,channel,level_v,slope,sweep))

    def set_channel_display(self, channel, enabled):
        from labremote.operation.ds1052e.set_channel_display import set_channel_display
        return self._submit('CHANNEL',lambda w:set_channel_display(w.ps,channel,enabled))

    def run(self):
        from labremote.operation.ds1052e.run import run
        return self._submit('RUN',lambda w:run(w.ps))

    def stop(self):
        from labremote.operation.ds1052e.stop import stop
        return self._submit('STOP',lambda w:stop(w.ps))

    def read_waveforms(self, channels=('CH1','CH2')):
        from labremote.operation.ds1052e.read_waveforms import read_waveforms
        return self._submit('FETCH',lambda w:read_waveforms(w.ps,channels),
                            arguments={'waveform_run_id':getattr(self.group,'waveform_run_id',None)})


class MSO7054API(DS1052EAPI):
    def start_waveform(self,channels=('CH1','CH2','CH3','CH4'),*,interval_s=1.0):
        return self.worker.waveform_runner.start(channels,interval_s,self.group)

    def read_waveforms(self,channels=('CH1','CH2','CH3','CH4')):
        from labremote.operation.mso7054.read_waveforms import read_waveforms
        return self._submit('FETCH',lambda w:read_waveforms(w.ps,channels),
                            arguments={'waveform_run_id':getattr(self.group,'waveform_run_id',None)})

    def configure_horizontal(self, time_scale_s, time_offset_s):
        from labremote.operation.mso7054.configure_horizontal import configure_horizontal
        return self._submit('HORIZONTAL',lambda w:configure_horizontal(w.ps,time_scale_s,time_offset_s))

    def configure_vertical(self, channel, scale_vdiv, offset_v):
        from labremote.operation.mso7054.configure_vertical import configure_vertical
        return self._submit('VERTICAL',lambda w:configure_vertical(w.ps,channel,scale_vdiv,offset_v))

    def configure_trigger(self, channel, level_v, *, slope='POS', sweep='AUTO'):
        from labremote.operation.mso7054.configure_trigger import configure_trigger
        return self._submit('TRIGGER',lambda w:configure_trigger(w.ps,channel,level_v,slope,sweep))

    def set_channel_display(self, channel, enabled):
        from labremote.operation.mso7054.set_channel_display import set_channel_display
        return self._submit('CHANNEL',lambda w:set_channel_display(w.ps,channel,enabled))

    def run(self):
        from labremote.operation.mso7054.run import run
        return self._submit('RUN',lambda w:run(w.ps))

    def stop(self):
        from labremote.operation.mso7054.stop import stop
        return self._submit('STOP',lambda w:stop(w.ps))


class ThermotekAPI(DeviceAPI):
    def read_telemetry(self, selection=()):
        from labremote.operation.thermotek.read_snapshot import read_snapshot
        return self._submit('TELEMETRY',lambda w:read_snapshot(w.ps))

    def start_monitoring(self, *, interval_s=None):
        if interval_s is None:interval_s=load_rf_device_config('thermotek',self.worker.name)['acquisition']['interval_s']
        return self.worker.waveform_runner.start((),interval_s,self.group)

    def stop_monitoring(self):return self.worker.waveform_runner.cancel()

    def cancel(self):
        if self.worker.waveform_runner.running():return self.stop_monitoring()
        return super().cancel()

    def set_target(self, target):
        from labremote.operation.thermotek.set_target import set_target
        return self._submit('SET_TARGET',lambda w:set_target(w.ps,target))

    def start(self):
        from labremote.operation.thermotek.start import start
        return self._submit('START',lambda w:start(w.ps))

    def stop(self):
        from labremote.operation.thermotek.stop import stop
        return self._submit('STOP',lambda w:stop(w.ps))


class KeithleyAPI(DeviceAPI):

    def set_voltage(self, value):
        from labremote.operation.keithley.set_voltage import set_voltage
        return self._submit('SET_VOLTAGE',lambda w:set_voltage(w.ps,self.channel,value))

    def set_current(self, value):
        from labremote.operation.keithley.set_current import set_current
        return self._submit('SET_CURRENT',lambda w:set_current(w.ps,self.channel,value))

    def set_voltage_limit(self, value):
        from labremote.operation.keithley.set_voltage_limit import set_voltage_limit
        return self._submit('SET_VOLTAGE_LIMIT',lambda w:set_voltage_limit(w.ps,self.channel,value))

    def set_voltage_limit_enabled(self, value):
        from labremote.operation.keithley.set_voltage_limit_enabled import set_voltage_limit_enabled
        return self._submit('SET_VOLTAGE_LIMIT_ENABLED',lambda w:set_voltage_limit_enabled(w.ps,self.channel,value))

    def on(self):
        from labremote.operation.keithley.on import on
        return self._submit('ON',lambda w:on(w.ps,self.channel))

    def off(self):
        from labremote.operation.keithley.off import off
        return self._submit('OFF',lambda w:off(w.ps,self.channel))

    def all_off(self):
        from labremote.operation.keithley.all_off import all_off
        return self._submit('ALL_OFF',lambda w:all_off(w.ps))


class OSAAPI(DeviceAPI):
    def read_spectrum(self, selection=()):
        from labremote.operation.osa.read_spectrum import read_spectrum
        return self._submit('SPECTRUM',lambda w:read_spectrum(w.ps),arguments={'waveform_run_id':getattr(self.group,'waveform_run_id',None)})

    def start_spectrum(self, *, interval_s=.3):
        return self.worker.waveform_runner.start((),interval_s,self.group)

    def stop_spectrum(self):
        self.worker.waveform_runner.cancel()
        # This independent abort follows any in-flight request/readback in the FIFO.
        return OSAAPI(self.worker).abort()

    def cancel(self):
        self.worker.waveform_runner.cancel()
        super().cancel()
        return OSAAPI(self.worker).abort()

    def abort(self):
        from labremote.operation.osa.abort import abort
        return self._submit('ABORT',lambda w:abort(w.ps))

    def set_range(self, low_thz, high_thz):
        from labremote.operation.osa.set_range import set_range
        return self._submit('SET_RANGE',lambda w:set_range(w.ps,low_thz,high_thz))

    def set_level(self, reference_dbm, db_per_div):
        from labremote.operation.osa.set_level import set_level
        return self._submit('SET_LEVEL',lambda w:set_level(w.ps,reference_dbm,db_per_div))

    def set_auto_reference(self, enabled):
        from labremote.operation.osa.set_auto_reference import set_auto_reference
        return self._submit('AUTO_REFERENCE',lambda w:set_auto_reference(w.ps,enabled))

    def set_trace(self, name):
        from labremote.operation.osa.set_trace import set_trace
        return self._submit('TRACE',lambda w:set_trace(w.ps,name))

    def zero(self):
        from labremote.operation.osa.zero import zero
        return self._submit('ZERO',lambda w:zero(w.ps))


class MDTAPI(DeviceAPI):
    def start_pid(self, osa, settings=None):
        return self.worker.pid_runner.start(osa,settings or {},self.group)

    def stop_pid(self):return self.worker.pid_runner.cancel()

    def update_pid(self, **changes):return self._submit('UPDATE_PID',lambda w:w.pid_runner.update_settings(changes),arguments=changes)

    def pid_step(self, axis, voltage, *, expected, max_delta, minimum, maximum, guard):
        from labremote.operation.mdt.pid_step import pid_step
        return self._submit('PID_STEP',lambda w:pid_step(w.ps,axis,voltage),arguments={
            'pid_guard':dict(expected=expected,max_delta=max_delta,minimum=minimum,maximum=maximum)},write_guard=guard)

    def set_voltage(self, axis, voltage):
        from labremote.operation.mdt.set_voltage import set_voltage
        return self._submit('SET_VOLTAGE',lambda w:set_voltage(w.ps,axis,voltage))

    def set_master_scan(self, enabled):
        from labremote.operation.mdt.set_master_scan import set_master_scan
        return self._submit('MASTER_SCAN',lambda w:set_master_scan(w.ps,enabled))


class FPGAAPI(DeviceAPI):
    def run_sequence_file(self, path, *, parameters=None, timeout_s=30., max_rows=4096):
        """Run a trusted builder file on the local FPGA worker, never a new serial connection."""
        from labremote.devices.fpga.sequence_file import validate_request
        from labremote.operation.fpga.run_sequence_file import run_sequence_file
        request=validate_request(path,parameters,timeout_s,max_rows)
        def execute(w):
            if w.waveform_runner.running() or any(r.running() for r in w.scan_runners.values()):
                raise RuntimeError('Stop FPGA repeat measurement / motor scans before running a sequence file')
            return run_sequence_file(w.ps,request)
        return self._submit('RUN_SEQUENCE_FILE',execute,arguments=request)

    def start_scan(self, x_motor, y_motor, settings=None, *, z_motor=None):
        settings=dict(settings or {});number=settings.get('scan',1)
        if type(number) is not int or number not in self.worker.scan_runners:raise ValueError('Scan must be 1, 2, 3 or 4')
        return self.worker.scan_runners[number].start(x_motor,y_motor,settings,self.group,z_motor=z_motor)

    def stop_scan(self, scan=None):
        if scan is None:
            from labremote.runtime.jobs import aggregate_handles
            handles=[runner.cancel() for runner in self.worker.scan_runners.values() if runner.running()]
            return aggregate_handles('STOP_SCANS',handles)
        if type(scan) is not int or scan not in self.worker.scan_runners:raise ValueError('Scan must be 1, 2, 3 or 4')
        return self.worker.scan_runners[scan].cancel()

    def connect_serial(self, port, name='fpga_local'):
        return self.connect(port,0,name)

    def set_output(self, name, enabled):
        from labremote.operation.fpga.set_output import set_output
        return self._submit('SET_OUTPUT',lambda w:set_output(w.ps,name,enabled))

    def measure(self, channel=0, exposure_ms=100):
        from labremote.operation.fpga.measure import measure
        return self._submit('MEASURE',lambda w:measure(w.ps,channel,exposure_ms))

    def measure_counts(self, channel=0, exposure_ms=100, average=1):
        from labremote.operation.fpga.measure_counts import measure_counts
        return self._submit('MEASURE_COUNTS',lambda w:measure_counts(w.ps,channel,exposure_ms,average))

    def start_count_tracking(self, channel=0, exposure_ms=100, average=1, *, interval_s=.5):
        return self.worker.waveform_runner.start((channel,exposure_ms,average),interval_s,self.group)

    def measure_repeated(self, selection):
        return self.measure_counts(*selection) if len(selection)==3 else self.measure(*selection)

    def start_measurement(self, channel=0, exposure_ms=100, *, interval_s=.5):
        return self.worker.waveform_runner.start((channel,exposure_ms),interval_s,self.group)

    def stop_measurement(self):return self.worker.waveform_runner.cancel()

    def cancel(self):
        self.worker.waveform_runner.cancel()
        return super().cancel()


class MotorAPI(DeviceAPI):
    def connect_motor(self, host, port, name):
        return self.connect(host, port, name)

    def move(self, position, *, tolerance=None):
        from labremote.operation.motors.move import move
        return self._submit('MOVE',lambda w:move(w.ps,position),arguments={'readback_tolerance':tolerance})

    def move_relative(self, distance):
        from labremote.operation.motors.move_relative import move_relative
        return self._submit('MOVE_RELATIVE',lambda w:move_relative(w.ps,distance))

    def status(self):return self.acquire('status')

    def open(self):
        from labremote.operation.motors.open import open
        return self._submit('OPEN',lambda w:open(w.ps))

    def close(self):
        from labremote.operation.motors.close import close
        return self._submit('CLOSE',lambda w:close(w.ps))

    def home(self):
        from labremote.operation.motors.home import home
        return self._submit('HOME',lambda w:home(w.ps))

    def stop(self):
        from labremote.operation.motors.stop import stop
        return self._submit('STOP',lambda w:stop(w.ps))
