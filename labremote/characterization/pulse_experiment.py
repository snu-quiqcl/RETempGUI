"""Independent Ramsey/SPAM profiles and analysis, with external microwave control."""
import math
from copy import deepcopy
import numpy as np
from . import config,rabi
from .ramsey_fit import fit_ramsey,population_and_error

KINDS=('ramsey','spam','initialization')
def title(kind):return {'ramsey':'Ramsey','spam':'SPAM','initialization':'Initialization'}[kind]
def defaults(kind,chamber):
    if kind not in KINDS or chamber not in ('EA','EC'):raise ValueError('Unknown experiment/chamber')
    if kind=='initialization':
        return dict(schema_version=1,experiment=kind,chamber=chamber,roles=rabi.defaults(chamber)['roles'],T_cool=50000,T_cool_repeat=6,T_init_step=20,T_det=8000,T_det_repeat=1,WAIT_AOM=100,N_average=500,N_init_control=21,N_threshold=4,timeout_s=120.)
    c=dict(schema_version=1,experiment=kind,chamber=chamber,roles=rabi.defaults(chamber)['roles'],
           T_cool=40000 if kind=='ramsey' else 50000,T_cool_repeat=10 if kind=='ramsey' else 2,
           T_init=1000 if kind=='ramsey' else 150,T_det=5000 if kind=='ramsey' else 8000,
           N_average=100 if kind=='ramsey' else 500,N_threshold=2,timeout_s=120. if kind=='ramsey' else 30.)
    if kind=='ramsey':c.update(T_det_repeat=1,T_wait_for_aom_off=100,half_pi_time=2948,precession_time=50000,max_precession_count=20,fit_low_hz=0.,fit_high_hz=0.)
    else:c.update(WAIT_AOM=50,T_PI=7677 if chamber=='EA' else 5996,N_repeat=10)
    return c

def times(kind):
    if kind=='initialization':return ('T_cool','T_init_step','T_det','WAIT_AOM')
    return ('T_cool','T_init','T_det')+(('T_wait_for_aom_off','half_pi_time','precession_time') if kind=='ramsey' else ('WAIT_AOM','T_PI'))

def fields(kind):
    if kind=='initialization':
        return [('T_cool','Cooling (us)',0,655.35,2,1),('T_cool_repeat','Cooling repeats',1,65535,0,1),('T_init_step','Initialization step (us)',.02,655.35,2,.01),('T_det','Detection (us)',0,655.35,2,1),('T_det_repeat','Detection repeats (original: fixed 1)',1,1,0,1),('WAIT_AOM','AOM wait (us)',0,655.35,2,.1),('N_average','Shots / point',1,65535,0,1),('N_init_control','Time points (from 0)',1,512,0,1),('N_threshold','Bright threshold (>=)',0,65535,0,1),('timeout_s','Timeout / scan (s)',.1,3600,1,1)]
    result=[('T_cool','Cooling (us)',0,655.35,2,1),('T_cool_repeat','Cooling repeats',1,65535,0,1),
            ('T_init','Initialization (us)',0,655.35,2,1),('T_det','Detection (us)',0,655.35,2,1)]
    if kind=='ramsey':result += [('T_det_repeat','Detection repeats',1,65535,0,1),('T_wait_for_aom_off','AOM off wait (us)',0,655.35,2,.1),
        ('half_pi_time','Half π pulse (us)',.07,655.35,2,.01),('precession_time','Precession step (us)',.02,655.35,2,1),
        ('max_precession_count','Delay points (from 0)',1,512,0,1),('fit_low_hz','Fit minimum (Hz)',0,5e7,3,1),('fit_high_hz','Fit maximum (Hz, 0=auto)',0,5e7,3,1)]
    else:result += [('WAIT_AOM','AOM wait (us)',0,655.35,2,.1),('T_PI','π pulse (us)',.07,655.35,2,.01),('N_repeat','Repeats / state',1,65535,0,1)]
    return result+[('N_average','Shots / point' if kind=='ramsey' else 'Attempts / batch',1,65535 if kind=='ramsey' else 1024,0,1),
        ('N_threshold','Bright threshold (>=)',0,65535,0,1),('timeout_s','Timeout / scan (s)' if kind=='ramsey' else 'Timeout / batch (s)',.1,3600,1,1)]

def validate(kind,value):
    if not isinstance(value,dict) or value.get('chamber') not in ('EA','EC'):raise ValueError('Invalid chamber')
    if set(value)!=set(defaults(kind,value['chamber'])) or value['schema_version']!=1 or value['experiment']!=kind:raise ValueError('Invalid experiment settings/schema')
    for key,_,low,high,dec,_ in fields(kind):
        v=value[key]
        if key in times(kind):low=round(low*100);high=round(high*100);dec=0
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not low<=v<=high or (not dec and type(v) is not int):raise ValueError('Invalid '+key)
    roles=value['roles']
    if not isinstance(roles,dict) or set(roles)!=set(rabi.ROLE_CHOICES) or any(roles[k] not in names for k,names in rabi.ROLE_CHOICES.items()):raise ValueError('Invalid FPGA roles')
    shots=value['N_average']*(value['N_init_control'] if kind=='initialization' else value['max_precession_count'] if kind=='ramsey' else 2*value['N_repeat'])
    if shots>2000000:raise ValueError('Maximum 2,000,000 attempts')
    c=value
    if kind=='initialization':
        duration=c['N_average']*sum(c['T_cool']*c['T_cool_repeat']+i*c['T_init_step']+c['T_det']+3*c['WAIT_AOM']+200 for i in range(c['N_init_control']))*1e-8
    elif kind=='ramsey':
        nyquist=.5/(c['precession_time']*1e-8)
        if c['fit_high_hz']==0:
            if c['fit_low_hz']!=0:raise ValueError('Auto fit range requires minimum=maximum=0')
        elif not 0<=c['fit_low_hz']<c['fit_high_hz']<=nyquist:raise ValueError('Fit range must be within the sampled Nyquist band')
        duration=c['N_average']*sum(c['T_cool']*c['T_cool_repeat']+c['T_init']+c['T_det']*c['T_det_repeat']+c['T_wait_for_aom_off']+2*c['half_pi_time']+i*c['precession_time']+200 for i in range(c['max_precession_count']))*1e-8
    else:duration=c['N_average']*(c['T_cool']*c['T_cool_repeat']+c['T_init']+c['T_det']+c['WAIT_AOM']+c['T_PI']+200)*1e-8
    if c['timeout_s']<=duration:raise ValueError('Timeout must exceed nominal acquisition time')
    return deepcopy(value)

def load(kind,chamber,path=None):
    local=config.ROOT/f'{kind}_{chamber}.local.json'
    c=validate(kind,config.read(path or (local if local.exists() else config.ROOT/f'{kind}_{chamber}.json')))
    if c['chamber']!=chamber:raise ValueError('Settings chamber differs from tab')
    return c

def clean(value):
    if isinstance(value,np.ndarray):return clean(value.tolist())
    if isinstance(value,np.generic):return clean(value.item())
    if isinstance(value,float) and not math.isfinite(value):return None
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    return value

def analyze(kind,records,c):
    if kind=='initialization':
        from .initialization_analysis import analyze
        return clean(analyze(records,c))
    if kind=='ramsey':
        rows=[r for r in records if r['counts']];t=np.array([r['index']*c['precession_time']*1e-8 for r in rows]);n=np.array([len(r['counts']) for r in rows]);k=np.array([sum(v>=c['N_threshold'] for v in r['counts']) for r in rows])
        p,e=population_and_error(k,n) if rows else (np.array([]),np.array([]))
        fit=fit_ramsey(t,k,n,None if c['fit_high_hz']==0 else (c['fit_low_hz'],c['fit_high_hz']),precession_step_s=c['precession_time']*1e-8)
        line_t=[];line_y=[]
        if fit.get('internal_parameters') is not None:
            low,high,cycles,phase,decay=fit['internal_parameters'];line_t=np.linspace(0,float(t.max()),500);u=line_t/fit['time_scale_s']
            line_y=(low+high)/2+(high-low)/2*np.exp(-decay*u)*np.cos(2*np.pi*cycles*u+phase)
        return clean(dict(experiment=kind,time_s=t,shot_counts=n,bright_counts=k,population=p,population_error=e,fit=fit,fit_time_s=line_t,fit_population=line_y,last_counts=rows[-1]['counts'] if rows else [],threshold=c['N_threshold']))
    states=[]
    for condition in (0,1):
        rows=[r for r in records if r['condition']==condition];counts=[v for r in rows for v in r['counts']]
        attempts=sum(r['attempts'] for r in rows);success=sum(r['successes'] for r in rows);bright=sum(v>=c['N_threshold'] for v in counts);n=len(counts)
        errors=bright if condition==0 else n-bright;rate=errors/n if n else None
        states.append(dict(condition=condition,counts=counts,N_attempts=attempts,N_success=success,N_received=n,N_bright=bright,N_error=errors,
            received_rows=sum(r['received_rows'] for r in rows),complete_batches=sum(r['complete'] for r in rows),
            success_probability=success/attempts if attempts else None,population=bright/n if n else None,spam_error=rate,conditional_fidelity=1-rate if rate is not None else None,
            histogram=np.bincount(np.minimum(np.asarray(counts,dtype=np.int64),39),minlength=40),batch_history=[{k:v for k,v in r.items() if k!='counts'} for r in rows]))
    error=(states[0]['spam_error']+states[1]['spam_error'])/2 if all(s['spam_error'] is not None for s in states) else None
    return clean(dict(experiment=kind,states=states,threshold=c['N_threshold'],average_spam_error=error,spam_fidelity=1-error if error is not None else None))

def draw(figure,data):
    figure.clear()
    if data['experiment']=='initialization':
        from .initialization_analysis import draw
        draw(figure,data);return
    if data['experiment']=='ramsey':
        hist,ax=figure.subplots(2,1);counts=data['last_counts']
        bins=np.bincount(np.minimum(np.asarray(counts,dtype=np.int64),40),minlength=41);hist.bar(np.arange(41),bins);hist.set(xlabel='Photon counts (40 includes overflow)',ylabel='Occurrences')
        ax.errorbar(np.array(data['time_s'])*1000,data['population'],yerr=data['population_error'],fmt='o-',label='Measured')
        if data['fit_time_s']:ax.plot(np.array(data['fit_time_s'])*1000,data['fit_population'],'--',label='Fit')
        ax.set(xlabel='Nominal free precession time (ms)',ylabel='Bright population',ylim=(-.05,1.05));ax.legend();ax.grid(True,alpha=.3)
    else:
        from .live_pulse import LivePlot
        plot=LivePlot(figure,'spam')
        plot.update(dict(states=data['states'],errors=[s['spam_error'] for s in data['states']]+[data['average_spam_error']]))
    # Stable margins also work when workflow results arrive in a hidden tab.
    figure.subplots_adjust(left=.12,right=.97,bottom=.09,top=.96,hspace=.45)

def summary(data):
    if data['experiment']=='initialization':
        fit=data['fit'];return ('Initialization tau = %.5g us' % fit['tau_us']) if fit['status']=='completed' else 'Initialization fit: '+fit['message']
    if data['experiment']=='ramsey':
        f=data['fit'];message=f"Fit: {f['status']}"
        if f.get('frequency_resolved'):message+=f" · Ramsey {f['frequency_hz']:.5g} Hz"
        if f.get('t2_resolved'):message+=f" · T2* {f['t2_star_s']*1000:.5g} ms"
        elif f.get('status')!='failed':message+=' · T2* unresolved'
        return message+'\n'+f.get('message','')
    lines=[]
    for s in data['states']:
        rate='N/A' if s['spam_error'] is None else f"{s['spam_error']:.4%}"
        lines.append(f"Target {s['condition']}: received {s['N_received']} / accepted {s['N_success']} / attempts {s['N_attempts']} · error {rate}")
    lines.append('Equal-weight SPAM fidelity: '+('N/A' if data['spam_fidelity'] is None else f"{data['spam_fidelity']:.4%}"))
    return '\n'.join(lines)
