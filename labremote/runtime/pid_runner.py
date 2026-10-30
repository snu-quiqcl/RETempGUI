"""OSA-feedback PID workflow; all hardware work goes through ordinary APIs."""
from __future__ import annotations
import math
import time
from copy import deepcopy
from labremote.runtime.workflow_runner import WorkflowTask
from labremote.config.device_config import load_device_config,operation_config

class InvalidSpectrum(ValueError):pass


def validate_settings(settings):
    c=dict(settings)
    if c['axis'] not in ('X','Y','Z'):raise ValueError('Select PID axis X/Y/Z')
    if type(c['polarity']) is not int or c['polarity'] not in (-1,1):raise ValueError('PID polarity must be -1/+1')
    if type(c['average_count']) is not int or not 1<=c['average_count']<=100:raise ValueError('PID average must be 1..100')
    if type(c['use_fit']) is not bool:raise ValueError('PID use_fit must be bool')
    for key in set(c)-{'axis','osa_name','polarity','average_count','use_fit'}:
        if isinstance(c[key],bool) or not isinstance(c[key],(int,float)) or not math.isfinite(c[key]):raise ValueError('Invalid PID setting: '+key)
    if c['target_thz']<=0:raise ValueError('Set a positive target frequency')
    if min(c[k] for k in ('kp_v_per_ghz','ki_v_per_ghz_s','kd_v_s_per_ghz'))<0:raise ValueError('PID gains must be nonnegative')
    if not any(c[k] for k in ('kp_v_per_ghz','ki_v_per_ghz_s','kd_v_s_per_ghz')):raise ValueError('Apply nonzero PID gains first')
    for key in ('capture_ghz','deadband_ghz','max_step_v','max_slew_v_per_s','max_gap_s','lease_s','derivative_filter_s'):
        if c[key]<=0:raise ValueError(key+' must be positive')
    if c['capture_ghz']<=c['deadband_ghz'] or not 0<=c['min_v']<c['max_v']<=150:raise ValueError('Invalid PID capture/voltage bounds')
    if not -150<=c['min_peak_dbm']<=50 or not 0<=c['minimum_snr_db']<=100 or not 2<=c['lease_s']<=120:raise ValueError('Invalid PID signal/heartbeat limits')
    return c


def estimate_peak(spectrum: dict[str, Any], use_fit: bool, min_snr: float):
    import numpy as np
    x = np.asarray(spectrum.get("frequency_thz", []), dtype=float)
    y = np.asarray(spectrum.get("power_dbm", []), dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    x, y = x[finite], y[finite]
    if x.size < 9:
        raise InvalidSpectrum("Insufficient OSA spectrum points")
    order = np.argsort(x)
    x, y = x[order], y[order]
    idx = int(y.argmax())
    floor = float(np.percentile(y, 20))
    peak = float(y[idx])
    raw = float(x[idx])
    snr = peak - floor
    if idx <= max(2, x.size // 50) or idx >= x.size - 1 - max(2, x.size // 50):
        raise InvalidSpectrum("Peak at measurement boundary")
    if snr < min_snr:
        raise InvalidSpectrum(f"Insufficient SNR: {snr:.2f} dB")
    fit = None
    if use_fit:
        try:
            from scipy.optimize import curve_fit
            import numpy as np
            def model(z, center, fwhm_ghz, dbm):
                p = 1.762747 * (z - center) * 1000.0 / fwhm_ghz
                return dbm - (20.0 / math.log(10.0)) * (np.logaddexp(p, -p) - math.log(2.0))
            left = max(0, idx - 60)
            right = min(len(x), idx + 61)
            xx, yy = x[left:right], y[left:right]
            w = max(float(np.median(np.diff(x))), 1e-9) * 5 * 1000.0
            pars, _ = curve_fit(model, xx, yy,
                                p0=[raw, w, peak],
                                bounds=([float(xx[0]), 1e-5, peak-10],
                                        [float(xx[-1]), max(1., (xx[-1]-xx[0])*5000.), peak+10]),
                                maxfev=5000)
            fit = float(pars[0])
            if not np.isfinite(pars).all():
                raise ValueError("Fit returned non-finite values")
        except Exception as exc:
            raise InvalidSpectrum(f"Fit required but unavailable: {exc}") from exc
    return {"raw_thz": raw, "fit_thz": fit, "peak_dbm": peak,
            "noise_floor_dbm": floor, "snr_db": snr,
            "selected_thz": fit if use_fit else raw}

class PIDMath:
    """v5 nonoverlapping averaging, filtered derivative and reachable-I limiting."""
    def __init__(self,c,voltage,now):
        self.c=dict(c);self.initial=self.current=voltage
        self.last_dt=self.last_out=now;self.integral=0.;self.previous=None;self.derivative=0.
        self.batch=[];self.gap=False

    def reset_batch(self):
        self.batch.clear();self.previous=None;self.derivative=0.;self.gap=True

    def update(self,c):
        if any(self.c[k]!=c[k] for k in ('target_thz','kp_v_per_ghz','ki_v_per_ghz_s','kd_v_s_per_ghz')):self.reset_batch()
        self.c=dict(c)

    def feed(self,spectrum,now):
        c=self.c;peak=estimate_peak(spectrum,c['use_fit'],c['minimum_snr_db'])
        if peak['peak_dbm']<c['min_peak_dbm']:raise InvalidSpectrum('Peak below minimum power')
        single_error=(c['target_thz']-peak['selected_thz'])*1000
        if not math.isfinite(single_error) or abs(single_error)>c['capture_ghz']:raise InvalidSpectrum('Outside PID capture range')
        self.batch.append(peak['selected_thz']);measured=sum(self.batch)/len(self.batch)
        data=dict(**peak,batch_collected=len(self.batch),batch_size=c['average_count'],measured_thz=measured)
        if len(self.batch)<c['average_count']:return None,data
        self.batch.clear();err=(c['target_thz']-measured)*1000
        dt=0. if self.gap else max(.001,now-self.last_dt);self.gap=False;self.last_dt=now
        deadband=abs(err)<=c['deadband_ghz']
        if deadband:err=0.
        if self.previous is not None and dt>0:
            raw=(err-self.previous)/dt;self.derivative+=dt/(c['derivative_filter_s']+dt)*(raw-self.derivative)
        self.previous=err
        def target(i):return self.initial+c['polarity']*(c['kp_v_per_ghz']*err+c['ki_v_per_ghz_s']*i+c['kd_v_s_per_ghz']*self.derivative)
        delta=min(c['max_step_v'],c['max_slew_v_per_s']*max(.005,now-self.last_out))
        lower=max(c['min_v'],self.current-delta);upper=min(c['max_v'],self.current+delta)
        base=target(self.integral);di=c['polarity']*c['ki_v_per_ghz_s']*err*dt
        accepted=min(di,max(0.,upper-base)) if di>0 else max(di,min(0.,lower-base)) if di<0 else 0.
        if c['ki_v_per_ghz_s']>0:self.integral+=accepted/(c['polarity']*c['ki_v_per_ghz_s'])
        requested=target(self.integral);proposed=self.current if deadband else max(lower,min(upper,requested))
        data.update(error_ghz=err,target_thz=c['target_thz'],dt_s=dt,requested_v=requested,max_change_v=delta,
            p_v=c['polarity']*c['kp_v_per_ghz']*err,i_v=c['polarity']*c['ki_v_per_ghz_s']*self.integral,
            d_v=c['polarity']*c['kd_v_s_per_ghz']*self.derivative,integral_limited=abs(accepted-di)>1e-12,
            output_limited=abs(proposed-requested)>1e-12 and not deadband)
        return proposed,data


class PIDRunner(WorkflowTask):
    def __init__(self,worker):super().__init__(worker,'MDT_PID')

    def start(self,osa,settings,parent=None):
        if osa.worker.family!='osa':raise ValueError('Select an OSA API')
        with operation_config():defaults=load_device_config('mdt',self.worker.name)['pid_defaults']
        unknown=set(settings)-set(defaults)
        c={**defaults,**settings,'osa_name':osa.worker.name}
        def run():
            if unknown:raise ValueError('Unknown PID settings: '+str(sorted(unknown)))
            self.osa_worker=osa.worker
            self.current_config=validate_settings(c)
            return self.run_pid()
        return self.launch(run,(self.worker,osa.worker),c,parent)

    def update_settings(self,changes):
        allowed={'target_thz','kp_v_per_ghz','ki_v_per_ghz_s','kd_v_s_per_ghz'}
        if not self.running() or not hasattr(self,'current_config') or set(changes)-allowed:raise ValueError('Only target/gains may change while PID is running')
        with self.state_lock:
            self.current_config=validate_settings({**self.current_config,**changes})
            return dict(self.current_config)

    def guard(self):
        self.check()
        with self.state_lock:c=dict(self.current_config)
        beat=self.worker.ui_heartbeat
        if beat is not None and time.monotonic()-beat>c['lease_s']:raise RuntimeError('GUI heartbeat lost; voltage HOLD')
        source=self.osa_worker.feedback_snapshot(include_spectrum=False)
        if not source['active'] or source['run_id']!=self.source_run:raise RuntimeError('OSA repeat stopped/disconnected/restarted; voltage HOLD')
        if time.monotonic()-self.last_valid>c['max_gap_s']:raise RuntimeError('No valid OSA spectrum within maximum gap; voltage HOLD')
        return source

    def run_pid(self):
        from labremote.api.devices import device_api
        api=device_api(self.worker,group=self.group)
        c=dict(self.current_config);source=self.osa_worker.feedback_snapshot(include_spectrum=False)
        if not source['active']:raise RuntimeError('Start OSA Repeat before PID')
        self.source_run=source['run_id'];frame=source['frame'];last_id=frame['request_id'] if frame else None
        self.last_valid=time.monotonic()
        if self.call(api.acquire('master_scan_enabled')):raise RuntimeError('Disable Master Scan before PID')
        voltage=self.call(api.acquire(c['axis'].lower()+'.voltage'))
        if not c['min_v']<=voltage<=c['max_v']:raise RuntimeError('Current voltage outside PID bounds')
        math_pid=PIDMath(c,voltage,time.monotonic());self.publish(phase='ARMED: waiting for a new OSA trace',voltage_v=voltage,samples=0)
        samples=0
        while True:
            source=self.guard();frame=source['frame']
            if frame is None or frame['run_id']!=self.source_run or frame['request_id']==last_id:
                self.wait(.05);continue
            source=self.osa_worker.feedback_snapshot();frame=source['frame']
            if not source['active'] or source['run_id']!=self.source_run:raise RuntimeError('OSA repeat source changed')
            if frame is None or frame['run_id']!=self.source_run or frame['request_id']==last_id:continue
            last_id=frame['request_id'];now=time.monotonic()
            with self.state_lock:c=dict(self.current_config)
            math_pid.update(c)
            if now-frame['acquired_at']>c['max_gap_s']:raise RuntimeError('Stale OSA spectrum; voltage HOLD')
            if self.call(api.acquire('master_scan_enabled')):raise RuntimeError('Master Scan enabled; voltage HOLD')
            try:proposed,data=math_pid.feed(frame['spectrum'],now)
            except InvalidSpectrum as exc:
                math_pid.reset_batch();self.publish(phase='HOLD: '+str(exc),batch_collected=0);continue
            self.last_valid=frame['acquired_at']
            if proposed is None:
                self.publish(phase='AVERAGING',**data);continue
            self.guard()
            if abs(proposed-math_pid.current)>.001:
                actual=self.call(api.pid_step(c['axis'],proposed,expected=math_pid.current,max_delta=data['max_change_v'],minimum=c['min_v'],maximum=c['max_v'],guard=self.guard))
                math_pid.current=actual;math_pid.last_out=now
            samples+=1
            self.publish(phase='RUNNING' if data['error_ghz'] else 'RUNNING: deadband',voltage_v=math_pid.current,samples=samples,request_id=last_id,**data)
