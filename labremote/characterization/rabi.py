"""Rabi settings, per-experiment routing, and original sin-squared analysis."""
import math
from copy import deepcopy
from types import SimpleNamespace
import numpy as np
from scipy.optimize import curve_fit
from . import config
from labremote.devices.fpga.controller import hd,OUTPUTS

ROLE_CHOICES={'PMT':config.PMTS,'AOM':config.AOMS,'MW':('MW_A','MW_C'),
              'EOM_7G_1':('EOM_7GA1','EOM_7GC1'),'EOM_7G_2':('EOM_7GA2','EOM_7GC2'),
              'EOM_2G':('EOM_2GA','EOM_2GC')}
TIMES=('T_cool','WAIT_AOM','T_init','T_det','T_mw_step')

def defaults(chamber):
    a=chamber=='EA';suffix='A' if a else 'C'
    return dict(schema_version=1,chamber=chamber,microwave='apsyn420_mw',
        frequency_start_hz=12642820855.,frequency_stop_hz=12642820855.,frequency_step_hz=1000.,
        settle_s=.1,timeout_s=30.,T_cool=50000,T_cool_repeat=2,WAIT_AOM=100,T_init=1000,T_det=6000,
        N_average=500,N_qubit_control=10,T_mw_step=1000,N_threshold=2,
        roles=dict(PMT='PMTF'+suffix,AOM='AOM'+suffix,MW='MW_'+suffix,
                   EOM_7G_1='EOM_7G'+suffix+'1',EOM_7G_2='EOM_7G'+suffix+'2',EOM_2G='EOM_2G'+suffix))

def frequencies(c):
    span=c['frequency_stop_hz']-c['frequency_start_hz'];step=c['frequency_step_hz']
    n=round(span/step)
    if n<0 or n>1000 or not math.isclose(span,n*step,abs_tol=.01):raise ValueError('Frequency span must be 0..1000 whole steps')
    return [c['frequency_start_hz']+i*step for i in range(n+1)]

def validate(value):
    if not isinstance(value,dict) or value.get('chamber') not in ('EA','EC'):raise ValueError('Rabi chamber must be EA or EC')
    if set(value)!=set(defaults(value['chamber'])) or value['schema_version']!=1:raise ValueError('Invalid Rabi fields/schema')
    if not isinstance(value['microwave'],str) or not value['microwave'].isidentifier():raise ValueError('Choose microwave instrument name')
    for k,lo,hi in [(k,7 if k=='T_mw_step' else 0,65535) for k in TIMES]+[('T_cool_repeat',1,65535),('N_average',1,1024),('N_qubit_control',3,65535),('N_threshold',0,65535)]:
        if type(value[k]) is not int or not lo<=value[k]<=hi:raise ValueError(f'{k}: integer {lo}..{hi} required')
    for k,lo,hi in [('frequency_start_hz',1e4,20e9),('frequency_stop_hz',1e4,20e9),('frequency_step_hz',.001,20e9),('settle_s',0,60),('timeout_s',.1,3600)]:
        v=value[k]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError('Invalid '+k)
    routes=value['roles']
    if not isinstance(routes,dict) or set(routes)!=set(ROLE_CHOICES) or any(routes[r] not in choices for r,choices in ROLE_CHOICES.items()):raise ValueError('Invalid Rabi hardware roles')
    if len({OUTPUTS[routes[r]][2] for r in ROLE_CHOICES if r!='PMT'})!=5:raise ValueError('Rabi output roles must use distinct pins')
    n=len(frequencies(value))*value['N_qubit_control']*value['N_average']
    if n>2000000:raise ValueError('Maximum 2,000,000 Rabi shots')
    duration=(value['T_cool']*value['T_cool_repeat']+value['T_init']+value['WAIT_AOM']+value['T_det']+value['T_mw_step']*(value['N_qubit_control']-1)+100)*1e-8*value['N_average']
    if value['timeout_s']<=duration:raise ValueError('Timeout must exceed longest nominal point acquisition time')
    return deepcopy(value)

def load(chamber,path=None):
    local=config.ROOT/f'rabi_{chamber}.local.json';public=config.ROOT/f'rabi_{chamber}.json'
    value=validate(config.read(path or (local if local.exists() else public)))
    if value['chamber']!=chamber:raise ValueError('Settings chamber does not match tab')
    return value

def hardware(roles):
    base=vars(config.sequence_hardware({r:roles[r] for r in ('PMT','AOM')}))
    base.update({r+'_out':getattr(hd,roles[r]+'_out') for r in ROLE_CHOICES if r not in ('PMT','AOM')})
    return SimpleNamespace(**base)

def fit(times_us,population):
    x=np.asarray(times_us,dtype=float)*1e-6;y=np.asarray(population,dtype=float)
    if len(x)<4 or np.ptp(y)<1e-6:return {'valid':False,'reason':'Insufficient points or contrast'}
    dt=x[1]-x[0];x=x/dt;nyquist=.5
    def model(t,a,f,c):return a*np.sin(np.pi*f*t)**2+c
    best=None
    # Multiple bounded seeds avoid the original zero-peak division and false fallback fit.
    spectrum=abs(np.fft.rfft(y-y.mean()))
    seeds=list(np.fft.rfftfreq(len(y))[np.argsort(spectrum[1:])[-5:]+1])+list(np.linspace(1/max(x[-1]*2,1),nyquist*.95,20))
    for seed in seeds:
        try:
            p,cov=curve_fit(model,x,y,p0=[np.ptp(y),min(seed,nyquist*.999),float(y.min())],bounds=([-1,1e-9,0],[1,nyquist,1]),maxfev=5000)
            residual=float(np.sum((model(x,*p)-y)**2))
            if best is None or residual<best[0]:best=(residual,p,cov)
        except (ValueError,RuntimeError,FloatingPointError):continue
    if best is None:return {'valid':False,'reason':'Fit did not converge'}
    residual,p,cov=best
    if not np.all(np.isfinite(cov)):return {'valid':False,'reason':'Fit uncertainty unavailable'}
    return dict(valid=True,amplitude=float(p[0]),frequency_hz=float(p[1]/dt),offset=float(p[2]),pi_time_us=float(.5*dt/p[1]*1e6),residual=residual)

def analyze(points,c):
    result=[]
    for frequency in frequencies(c):
        rows=[p for p in points if p['frequency_hz']==frequency]
        if not rows:continue
        times=[p['index']*c['T_mw_step']*.01 for p in rows]
        pop=[sum(n>=c['N_threshold'] for n in p['counts'])/len(p['counts']) for p in rows]
        result.append(dict(frequency_hz=frequency,time_us=times,population=pop,
            mean_count=[float(np.mean(p['counts'])) for p in rows],
            population_sem=[math.sqrt(p*(1-p)/len(row['counts'])) for p,row in zip(pop,rows)],
            fit=fit(times,pop),contrast=float(max(pop)-min(pop)),original_visibility=float((1+max(pop)-min(pop))/2)))
    return dict(curves=result,last_counts=points[-1]['counts'] if points else [],threshold=c['N_threshold'])

def draw(figure,data):
    figure.clear();hist,osc,sweep=figure.subplots(3,1)
    counts=data.get('last_counts',[])
    if counts:
        values,bins=np.unique(counts,return_counts=True);hist.bar(values,bins)
    hist.axvline(data['threshold'],color='r',linestyle='--');hist.set(xlabel='Photon counts',ylabel='Occurrences')
    for curve in data['curves']:
        x=np.asarray(curve['time_us']);osc.errorbar(x,curve['population'],yerr=curve['population_sem'],fmt='o-',label=f"{curve['frequency_hz']/1e9:.9f} GHz")
        f=curve['fit']
        if f['valid']:
            t=np.linspace(0,x[-1],300);osc.plot(t,f['amplitude']*np.sin(np.pi*f['frequency_hz']*t*1e-6)**2+f['offset'],'--')
    if data['curves']:osc.legend(fontsize=7)
    osc.set(xlabel='Nominal microwave pulse time (us)',ylabel='Bright population',ylim=(-.05,1.05))
    curves=data['curves'];sweep.plot([p['frequency_hz']/1e9 for p in curves],[p['original_visibility'] for p in curves],'o-',color='C0')
    sweep.set(xlabel='Microwave frequency (GHz)',ylabel='Original visibility metric')
    fitted=[p for p in curves if p['fit']['valid']];frequency_axis=sweep.twinx()
    frequency_axis.plot([p['frequency_hz']/1e9 for p in fitted],[p['fit']['frequency_hz']/1000 for p in fitted],'o-',color='C1')
    frequency_axis.set_ylabel('Rabi frequency (kHz)',color='C1');figure.tight_layout()
