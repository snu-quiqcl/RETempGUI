import numpy as np
from matplotlib.ticker import FuncFormatter
from .model import _geometry


def draw(figure,report,selected=None):
    figure.clear()
    ax=figure.subplots(2,2);amp,phase,rate,hist=ax.flat
    points=report.get('points',[])
    x=[p['frequency_khz'] for p in points]
    for axis,key,error,scale,title in [
        (amp,'modulation','modulation_se',100,'Fluorescence modulation'),
        (phase,'phase_rad','phase_se',180/np.pi,'Response phase')]:
        valid=[p for p in points if p.get('fit',{}).get('valid') and p['fit'].get(key) is not None]
        axis.errorbar([p['frequency_khz'] for p in valid],
            [p['fit'][key]*scale for p in valid],
            yerr=[np.nan if p['fit'].get(error) is None else p['fit'][error]*scale for p in valid],fmt='o-',ms=4,capsize=2)
        axis.set_title(title);axis.set_ylabel('%' if axis is amp else 'theta (deg)')
    rate.errorbar(x,[p['mean_rate_cps']/1000 for p in points],
        yerr=[p['rate_sem_cps']/1000 for p in points],fmt='o-',ms=4,capsize=2)
    rate.set_title('Mean PMT count rate');rate.set_ylabel('kcounts/s')
    for axis in (amp,phase,rate):
        axis.set_xlabel('Modulation frequency (kHz)');axis.grid(alpha=.2)
    if selected is not None and 0<=selected<len(points):point=points[selected]
    else:point=report.get('current_point') or (points[-1] if points else None)
    if point:
        values=point.get('histogram',[])
        if values:
            _,edges,_,_=_geometry(point['frequency_khz'],len(values))
            centers=(edges[:-1]+edges[1:])/2*1.25/1000
            hist.step(centers,values,where='mid',label='Accepted first photons')
            fit=point.get('fit',{})
            if fit.get('valid'):
                hist.plot(centers,fit['prediction'],label='First-photon corrected fit')
            hist.legend(fontsize=8)
        hist.set_title(f"{point['frequency_khz']:.6g} kHz · {point.get('events',0):,} events")
        for axis in (amp,phase,rate):axis.axvline(point['frequency_khz'],color='gray',alpha=.3)
    else:hist.set_title('Select a frequency to inspect its histogram')
    hist.set_xlabel('PMT - SYNC delay (µs)');hist.set_ylabel('Events / phase bin')
    for axis in ax.flat:
        axis.xaxis.set_major_formatter(FuncFormatter(lambda x,pos:f'{x:g}'))
        axis.yaxis.set_major_formatter(FuncFormatter(lambda x,pos:f'{x:g}'))
    figure.subplots_adjust(left=.09,right=.97,bottom=.10,top=.94,hspace=.55,wspace=.30)
    return dict(amplitude=amp,phase=phase,rate=rate,histogram=hist)
