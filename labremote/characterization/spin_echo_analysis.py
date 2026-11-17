"""Binomial exponential Hahn-echo fit with free offset and signed amplitude."""
import numpy as np
from scipy.optimize import least_squares
from scipy.special import xlogy
from .ramsey_fit import population_and_error


def analyze(records, c):
    rows=[r for r in records if r['counts']]
    t=np.array([r['index']*c['precession_time']*1e-8 for r in rows])
    n=np.array([len(r['counts']) for r in rows])
    k=np.array([sum(v>=c['N_threshold'] for v in r['counts']) for r in rows])
    p,e=population_and_error(k,n) if rows else (np.array([]),np.array([]))
    fit=dict(status='failed',t2_resolved=False,message='At least 6 distinct times are needed.')
    line_t=[];line_p=[]
    if len(np.unique(t))>=6 and np.ptp(t)>0:
        span=float(np.ptp(t));u=t/span
        def prediction(v,x):
            initial,offset,decay=v
            return offset+(initial-offset)*np.exp(-decay*x)
        def residual(v):
            prob=np.clip(prediction(v,u),1e-12,1-1e-12)
            d=2*(xlogy(k,k/(n*prob))+xlogy(n-k,(n-k)/(n*(1-prob))))
            return np.sign(k-n*prob)*np.sqrt(np.maximum(d,0))
        results=[least_squares(residual,[np.clip(p[0],.001,.999),np.clip(p[-1],.001,.999),decay],bounds=([0,0,.001],[1,1,100]),max_nfev=2000) for decay in (.1,1,5,20)]
        result=min(results,key=lambda r:float(np.dot(r.fun,r.fun)))
        initial,offset,decay=result.x;t2=span/decay
        rank=np.linalg.matrix_rank(result.jac)
        covariance=np.linalg.pinv(result.jac.T@result.jac)
        decay_error=float(np.sqrt(max(0,covariance[2,2])))
        amplitude_error=float(np.sqrt(max(0,covariance[0,0]+covariance[1,1]-2*covariance[0,1])))
        resolved=bool(result.success and rank==3 and .1<decay<99 and decay_error<decay and abs(initial-offset)>3*amplitude_error)
        fit=dict(status='completed' if result.success else 'failed',t2_resolved=resolved,
                 t2_echo_s=float(t2) if resolved else None,
                 t2_echo_error_s=float(span*decay_error/decay**2) if resolved else None,
                 offset=float(offset),amplitude=float(initial-offset),model='offset + amplitude * exp(-total_free_time / T2_echo)',
                 message='Exponential echo decay fit.' if resolved else 'Decay/contrast is not sufficiently resolved; extend the scan or collect more shots.')
        if result.success:
            line_t=np.linspace(0,float(t.max()),300);line_p=prediction(result.x,line_t/span)
    return dict(experiment='spin_echo',time_s=t,shot_counts=n,bright_counts=k,population=p,population_error=e,
                fit=fit,fit_time_s=line_t,fit_population=line_p,last_counts=rows[-1]['counts'] if rows else [],threshold=c['N_threshold'],
                timing=dict(clock_ns=10,total_step_ticks=c['precession_time'],half_pi_ticks=c['half_pi_time'],pi_ticks=2*c['half_pi_time'],zero_delay='continuous same-phase 2pi pulse'))
