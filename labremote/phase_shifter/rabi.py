"""Phase-resolved Rabi plans and independent damped oscillation fits."""
from copy import deepcopy
from decimal import Decimal
import math
import numpy as np
from scipy.optimize import curve_fit
from . import config
from .rabi_sequence import build_program

DEFAULTS = dict(config.DEFAULTS, pulse_start_us=0., pulse_stop_us=100., pulse_step_us=2.)

def times(c):
    if 'pulse_points' in c:
        count=c['pulse_points']
        if type(count) is not int or not 6 <= count <= 4097:
            raise ValueError('Pulse points는 6~4097 사이 정수여야 합니다.')
        c=dict(c,pulse_start_us=0.,pulse_stop_us=float(Decimal(str(c['pulse_step_us']))*(count-1)))
    vals = [c[k] for k in ('pulse_start_us','pulse_stop_us','pulse_step_us')]
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in vals):
        raise ValueError('펄스 시간은 유한한 숫자로 입력하세요.')
    start,stop,step = [Decimal(str(v))*100 for v in vals]
    if any(v != int(v) for v in (start,stop,step)):
        raise ValueError('펄스 시간 분해능은 0.01 µs입니다.')
    start,stop,step = map(int,(start,stop,step))
    if not 7 <= step <= 65535 or not 0 <= start <= stop <= step*65535:
        raise ValueError('Pulse step은 0.07~655.35 µs, 총 길이는 최대 65535 step입니다.')
    if start % step:
        raise ValueError('시작 시간은 Pulse step의 정수배여야 합니다.')
    if (stop-start)%step:
        raise ValueError('끝 시간은 시작 시간에서 간격의 정수배로 설정하세요.')
    result=list(range(start,stop+1,step))
    if not 6 <= len(result) <= 4097 or any(0<t<3 for t in result):
        raise ValueError('6~4097개 시간 지점, 0 이외의 펄스는 최소 0.03 µs가 필요합니다.')
    return result

def validate(value):
    c=deepcopy(value)
    ts=times(c)
    if 'pulse_points' in c:
        c.update(pulse_start_us=0.,pulse_stop_us=ts[-1]/100)
    c=config.validate(c)
    skipped=[]
    phases=config.scan_points(c,skipped)
    if len(ts)*len(phases)>200000:
        raise ValueError('총 측정 지점은 최대 200,000개입니다.')
    for t in (ts[0],ts[-1]):
        build_program(dict(c,pulse_clocks=t),config.hd).program(show=False)
    return c,phases,ts,skipped

def model(t, offset, amplitude, frequency, decay, phase):
    return offset+amplitude*np.exp(-t/decay)*np.cos(2*np.pi*frequency*t+phase)

def fit(points):
    if len(points)<6:return dict(valid=False,reason='측정 지점 부족')
    t=np.array([p['pulse_clocks']/100 for p in points]); y=np.array([p['probability'] for p in points])
    dt=t[1]-t[0]; span=t[-1]-t[0]
    if np.ptp(y)<.03:return dict(valid=False,reason='대비 부족')
    sigma=np.sqrt(np.maximum(y*(1-y),.01)/np.array([p['shots'] for p in points]))
    spectrum=abs(np.fft.rfft(y-y.mean()))
    seeds=np.fft.rfftfreq(len(y),dt)[np.argsort(spectrum[1:])[-5:]+1]
    best=None
    for f in seeds:
        for phase in (0.,np.pi):
            try:
                p,cov=curve_fit(model,t,y,p0=[y.mean(),np.ptp(y)/2,f,span*3,phase],
                    bounds=([0,0,1/(span*4),dt,-2*np.pi],[1,1,.5/dt,span*1000,2*np.pi]),
                    sigma=sigma,absolute_sigma=True,maxfev=4000)
                residual=float(np.sum(((y-model(t,*p))/sigma)**2))
                if best is None or residual<best[0]:best=residual,p,cov
            except (RuntimeError,ValueError):pass
    if best is None:return dict(valid=False,reason='피팅 실패')
    residual,p,cov=best
    error=float(np.sqrt(max(0,cov[2,2])))
    if not np.isfinite(error) or error>p[2]/2 or p[2]*span<1 or p[2]>=.49/dt:
        return dict(valid=False,reason='주파수 불확실 / 시간 범위·간격 확인')
    return dict(valid=True,frequency_khz=float(p[2]*1000),error_khz=error*1000,
                pi_time_us=float(.5/p[2]),parameters=p.tolist(),reduced_chi2=residual/max(1,len(t)-5))
