"""Original A exp(-t/tau)+offset analysis; zero time excluded from fit."""
import warnings
import numpy as np
from scipy.optimize import curve_fit, OptimizeWarning
from .ramsey_fit import population_and_error


def exponential(t,tau,amplitude,offset):
    return amplitude*np.exp(-t/tau)+offset


def analyze(records,c):
    rows=[r for r in records if r['counts']]
    t=np.asarray([r['index']*c['T_init_step']*.01 for r in rows])
    n=np.asarray([len(r['counts']) for r in rows])
    k=np.asarray([sum(x>=c['N_threshold'] for x in r['counts']) for r in rows])
    p,e=population_and_error(k,n) if rows else (np.array([]),np.array([]))
    fit=dict(status='unresolved',message='Need at least three positive-time points',tau_us=None)
    line_t=[];line_p=[]
    # Incomplete points remain in saved populations, but do not bias the fit.
    mask=np.asarray([r['complete'] for r in rows],dtype=bool)&(t>0)
    if sum(mask)>=3 and np.ptp(p[mask])>1e-12:
        x,y=t[mask],p[mask]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error',OptimizeWarning)
                params,cov=curve_fit(exponential,x,y,p0=[np.median(x),np.ptp(y),min(y)],bounds=([1e-12,-np.inf,0],[np.inf,np.inf,1]),maxfev=20000)
            if not np.all(np.isfinite(cov)):raise ValueError('Fit uncertainty unresolved')
            fit=dict(status='completed',message='Zero time and incomplete points excluded',tau_us=float(params[0]),amplitude=float(params[1]),offset=float(params[2]),covariance=cov)
            line_t=np.linspace(min(x),max(x),300);line_p=exponential(line_t,*params)
        except (ValueError,RuntimeError,OptimizeWarning) as exc:fit['message']=str(exc)
    elif sum(mask)>=3:fit['message']='Population has no resolved contrast'
    return dict(experiment='initialization',time_s=t*1e-6,shot_counts=n,bright_counts=k,population=p,population_error=e,fit=fit,fit_time_us=line_t,fit_population=line_p,last_counts=rows[-1]['counts'] if rows else [],threshold=c['N_threshold'])


def draw(figure,data):
    hist,ax=figure.subplots(2,1)
    counts=np.asarray(data['last_counts'],dtype=np.int64)
    hist.bar(np.arange(41),np.bincount(np.minimum(counts,40),minlength=41))
    hist.set(xlabel='Photon counts (40 includes overflow)',ylabel='Occurrences')
    ax.errorbar(np.asarray(data['time_s'])*1e6,data['population'],yerr=data['population_error'],fmt='o-',label='Measured')
    if len(data['fit_time_us']):ax.plot(data['fit_time_us'],data['fit_population'],'--',label='Exponential fit')
    values=np.concatenate((np.asarray(data['population'],dtype=float),np.asarray(data['fit_population'],dtype=float)))
    positive=values[np.isfinite(values)&(values>0)]
    lower=min(.1,float(positive.min())*.5) if positive.size else 1e-3
    upper=max(1.05,float(positive.max())*1.1) if positive.size else 1.05
    ax.set(xlabel='Nominal initialization time (us)',ylabel='Bright population',ylim=(lower,upper))
    ax.set_yscale('log',nonpositive='mask')
    if np.any(np.asarray(data['population'])<=0):
        ax.text(.02,.03,'Zero population is not shown on log scale',transform=ax.transAxes,fontsize=8)
    ax.grid(True,which='both',alpha=.3);ax.legend()
    figure.subplots_adjust(left=.12,right=.97,bottom=.09,top=.96,hspace=.45)
