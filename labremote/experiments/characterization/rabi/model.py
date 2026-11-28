from labremote.devices.fpga.mapping import settings_path
"""Rabi settings, per-experiment routing, and original sin-squared analysis."""
import math
from copy import deepcopy
from types import SimpleNamespace
import numpy as np
from labremote.experiments.detector_comparison import comparison_roles, comparison_counts, LABELS, COLORS, histogram_steps
from scipy.optimize import curve_fit
from labremote.experiments.characterization.shared import config
from labremote.devices.fpga.controller import hd, OUTPUTS

FAST_OUTPUTS=tuple(name for name,kind in config.ROLE_KINDS.items() if kind=='fast output')
FAST_OUTPUTS=config.RouteChoices(FAST_OUTPUTS, 'fast')
SLOW_OUTPUTS=config.RouteChoices(tuple(name for name,kind in config.ROLE_KINDS.items() if kind=='slow output'), 'slow')
ROLE_CHOICES={role:config.PMTS if role=='PMT' else SLOW_OUTPUTS if role=='MW' else FAST_OUTPUTS for role in ('PMT','AOM','MW','EOM_7G_1','EOM_7G_2','EOM_2G')}
TIMES=('T_cool','WAIT_AOM','T_init','T_det','T_mw_step')

def defaults(chamber):
    from labremote.configuration.default_profiles import read_default
    value=read_default('rabi_'+chamber)
    value['schema_version']=3
    value.setdefault('detector_count',1)
    value['roles'].setdefault('PMT2',None)
    return value

def validate_frequency(value):
    if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0):
        raise ValueError('frequency_hz is optional positive metadata, not a hardware setting')
    return value

def validate(value):
    if not isinstance(value,dict) or value.get('chamber') not in ('EA','EC'):raise ValueError('Rabi chamber must be EA or EC')
    value=deepcopy(value)
    if value.get('schema_version')==1:
        legacy={'microwave','frequency_start_hz','frequency_stop_hz','frequency_step_hz','settle_s'}
        if set(value)-{'detector_count'}!=(set(defaults(value['chamber']))-{'detector_count'})|legacy:raise ValueError('Invalid legacy Rabi settings')
        if value['frequency_start_hz']!=value['frequency_stop_hz']:raise ValueError('Move legacy frequency sweep to an external workflow; load a single-frequency profile')
        for key in legacy:value.pop(key)
        value['schema_version']=2
    if value.get('schema_version')==2:
        value.setdefault('detector_count',1)
        value['schema_version']=3
    if set(value)!=set(defaults(value['chamber'])) or value['schema_version']!=3:raise ValueError('Invalid Rabi fields/schema')
    if type(value['detector_count']) is not int or value['detector_count'] not in (1,2):raise ValueError('Select 1 or 2 PMTs')
    if not isinstance(value.get('roles'),dict):raise ValueError('Invalid Rabi roles')
    value['roles'].setdefault('PMT2',None)
    if value['detector_count']==1:value['roles']['PMT2']=None
    elif not value['roles']['PMT2']:
        from labremote.devices.fpga.mapping import EDITING
        if not EDITING.get():raise ValueError('Select PMT 2 for two-PMT Rabi')
    for k,lo,hi in [(k,7 if k=='T_mw_step' else 0,65535) for k in TIMES]+[('T_cool_repeat',1,65535),('N_average',1,1024),('N_qubit_control',3,65535),('N_threshold',0,65535)]:
        if type(value[k]) is not int or not lo<=value[k]<=hi:raise ValueError(f'{k}: integer {lo}..{hi} required')
    for k,lo,hi in [('timeout_s',.1,3600)]:
        v=value[k]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError('Invalid '+k)
    validate_roles(value['roles'],detector_count=value['detector_count'])
    n=value['N_qubit_control']*value['N_average']
    if n>2000000:raise ValueError('Maximum 2,000,000 Rabi shots')
    duration=(value['T_cool']*value['T_cool_repeat']+value['T_init']+value['WAIT_AOM']+value['T_det']+value['T_mw_step']*(value['N_qubit_control']-1)+100)*1e-8*value['N_average']
    if value['timeout_s']<=duration:raise ValueError('Timeout must exceed longest nominal point acquisition time')
    return deepcopy(value)

def load(chamber,path=None):
    local=settings_path(config.ROOT/f'rabi_{chamber}.json');public=config.ROOT/f'rabi_{chamber}.json'
    value=validate(config.read(path or (local if local.exists() else public)))
    if value['chamber']!=chamber:raise ValueError('Settings chamber does not match tab')
    return value

def validate_roles(roles,detector_count=1):
    if not isinstance(roles,dict) or set(roles)-{'PMT2'}!=set(ROLE_CHOICES) or any(roles[r] not in choices for r,choices in ROLE_CHOICES.items()):
        raise ValueError('Select a counter input, slow MW output, and fast AOM/EOM outputs')
    from labremote.devices.fpga.mapping import EDITING
    if detector_count==2:
        if roles.get('PMT2') not in config.PMTS:raise ValueError('Select a counter input for PMT 2')
        if not EDITING.get() and getattr(hd,roles['PMT']+'_counter_result')==getattr(hd,roles['PMT2']+'_counter_result'):
            raise ValueError('PMT 1 and PMT 2 must use distinct physical counter inputs')
    if not EDITING.get() and len({OUTPUTS[roles[r]][1:] for r in ROLE_CHOICES if r!='PMT'})!=5:
        raise ValueError('Pulse output roles must use distinct physical pins')


def hardware(roles):
    validate_roles(roles,detector_count=2 if roles.get('PMT2') else 1)
    base=vars(config.sequence_hardware({r:roles[r] for r in ('PMT','AOM')}))
    base.update({r+'_out':getattr(hd,roles[r]+'_out') for r in ROLE_CHOICES if r not in ('PMT','AOM')})
    base['MW_port']=OUTPUTS[roles['MW']][1]
    if roles.get('PMT2'):
        for suffix in ('counter_reset','counter_enable','counter_result'):
            base['PMT2_'+suffix]=getattr(hd,roles['PMT2']+'_'+suffix)
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

def detector_roles(c):
    return ('PMT','PMT2') if c.get('detector_count',1)==2 else ('PMT',)


def counts_by_detector(counts):
    """Legacy points keep a list; dual points keep paired per-detector lists."""
    return counts if isinstance(counts,dict) else {'PMT':counts}


def detector_label(role):
    return LABELS[role]


def analyze(points,c,frequency_hz=None):
    result=[];last={role:[] for role in comparison_roles(c)}
    if points:
        times=[p['index']*c['T_mw_step']*.01 for p in points]
        paired=[comparison_counts(p['counts']) for p in points]
        for role in comparison_roles(c):
            rows=[counts[role] for counts in paired]
            pop=[sum(n>=c['N_threshold'] for n in counts)/len(counts) for counts in rows]
            result.append(dict(detector=role,frequency_hz=frequency_hz,time_us=times,population=pop,
                mean_count=[float(np.mean(counts)) for counts in rows],
                population_sem=[math.sqrt(p*(1-p)/len(counts)) for p,counts in zip(pop,rows)],
                fit=fit(times,pop),contrast=float(max(pop)-min(pop)),original_visibility=float((1+max(pop)-min(pop))/2)))
            last[role]=rows[-1]
    return dict(curves=result,last_counts=last['PMT'],last_counts_by_detector=last,
                detector_count=len(detector_roles(c)),threshold=c['N_threshold'])


def load_analysis(folder):
    """Reanalyze older paired archives in memory; never overwrite saved results."""
    from pathlib import Path
    folder=Path(folder);data=config.read(folder/'analysis.json')
    if data.get('detector_count',1)==2 and not any(c.get('detector')=='SUM' for c in data['curves']):
        if (folder/'points.json').is_file() and (folder/'configuration.json').is_file():
            saved=config.read(folder/'configuration.json')
            data=analyze(config.read(folder/'points.json'),saved['settings'],saved.get('frequency_hz'))
    return data


def draw_dual(figure,data):
    hist,osc=figure.subplots(2,1)
    channels=comparison_counts(data.get('last_counts_by_detector',{'PMT':data.get('last_counts',[])}))
    for role,counts in channels.items():
        hist.step(*histogram_steps(counts),where="mid",color=COLORS[role],label=detector_label(role))
    hist.axvline(data['threshold'],color='0.4',linestyle='--',label='Shared threshold')
    hist.set(xlabel='Photon counts / shot',ylabel='Shots',title='Last point: individual PMTs and paired sum');hist.legend(fontsize=8)
    for curve in data['curves']:
        role=curve['detector'];color=COLORS[role];x=np.asarray(curve['time_us'])
        osc.errorbar(x,curve['population'],yerr=curve['population_sem'],fmt='o-',color=color,label=detector_label(role),markersize=3)
        f=curve['fit']
        if f['valid']:
            t=np.linspace(0,x[-1],300)
            osc.plot(t,f['amplitude']*np.sin(np.pi*f['frequency_hz']*t*1e-6)**2+f['offset'],'--',color=color,label=detector_label(role)+' fit')
    osc.legend(fontsize=8);osc.grid(True,alpha=.3)
    osc.set(xlabel='Nominal microwave pulse time (us)',ylabel='Bright population',ylim=(-.05,1.05))
    figure.tight_layout()


def draw(figure,data):
    figure.clear()
    if data.get('detector_count',1)==2:return draw_dual(figure,data)
    curves=data['curves'];scanned=len(curves)>1
    axes=figure.subplots(3 if scanned else 2,1);hist,osc=axes[:2]
    counts=data.get('last_counts',[])
    if counts:
        values,bins=np.unique(counts,return_counts=True);hist.bar(values,bins)
    hist.axvline(data['threshold'],color='r',linestyle='--');hist.set(xlabel='Photon counts',ylabel='Counts')
    for curve in data['curves']:
        x=np.asarray(curve['time_us']);osc.errorbar(x,curve['population'],yerr=curve['population_sem'],fmt='o-',label=(f"{curve['frequency_hz']/1e9:.9f} GHz (metadata)" if curve.get('frequency_hz') is not None else "External microwave"))
        f=curve['fit']
        if f['valid']:
            t=np.linspace(0,x[-1],300);osc.plot(t,f['amplitude']*np.sin(np.pi*f['frequency_hz']*t*1e-6)**2+f['offset'],'--')
    osc.grid(True,which='both',alpha=.3)
    if data['curves']:osc.legend(fontsize=7)
    osc.set(xlabel='Nominal microwave pulse time (us)',ylabel='Bright population',ylim=(-.05,1.05))
    if scanned:
        sweep=axes[2];sweep.plot([p['frequency_hz']/1e9 for p in curves],[p['original_visibility'] for p in curves],'o-',color='C0')
        sweep.set(xlabel='Microwave frequency (GHz)',ylabel='Original visibility metric')
        fitted=[p for p in curves if p['fit']['valid']];frequency_axis=sweep.twinx()
        frequency_axis.plot([p['frequency_hz']/1e9 for p in fitted],[p['fit']['frequency_hz']/1000 for p in fitted],'o-',color='C1')
        frequency_axis.set_ylabel('Rabi frequency (kHz)',color='C1')
    figure.tight_layout()
