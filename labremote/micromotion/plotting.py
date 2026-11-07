"""Visibility/phase maps share voltage axes and selection; phase is circular."""
import numpy as np
import matplotlib as mpl
from .config import grid
from .analysis import phase_statistics


def phase_scale(unit):
    return (180/np.pi,'deg') if unit=='deg' else (1.,'rad')


def phase_text(fit,unit='deg',mask=True):
    p=phase_statistics(fit);factor,label=phase_scale(unit)
    if not p['phase_reliable'] and mask:return 'Phase unresolved (low SNR / large phase error)'
    uncertainty='undefined' if p['phase_se'] is None else f"{p['phase_se']*factor:.2f}"
    return f"Phase {p['phase']*factor:.2f} ± {uncertainty} {label} (1 SE)"+(' · UNRESOLVED' if not p['phase_reliable'] else '')


def phase_bars(ax,x,phi,se,factor,color):
    """Split circular error intervals at +/-pi."""
    ax.plot(x,phi*factor,'.',color=color,ms=3)
    if se is None:return
    if se>=np.pi:
        ax.vlines(x,-np.pi*factor,np.pi*factor,color=color,alpha=.25,linewidth=.6)
        return
    for shift in (-2*np.pi,0.,2*np.pi):
        lo=max(-np.pi,phi-se+shift);hi=min(np.pi,phi+se+shift)
        if lo<=hi:ax.vlines(x,lo*factor,hi*factor,color=color,alpha=.45,linewidth=.6)


def draw(figure,report,selected=None,candidate=None,phase_unit='deg',mask_phase=True):
    figure.clear()
    c=report['settings'];points=report.get('points',[]);mode=report.get('mode','scan')
    if mode=='input':
        ax=figure.add_subplot(111);d=report.get('rf_test')
        if d:
            ax.plot(np.arange(len(d['counts'])),d['counts'],'.-',label='Received counts')
            ax.axhline(d['expected'],color='tab:orange',label='Expected');ax.legend()
            ax.set_title(f"RF input: mean {d['mean']:.2f}, std {d['std']:.2f}")
        ax.set(xlabel='Gate index',ylabel='RF counts');figure.tight_layout();return dict(map=None,phase_map=None)
    if mode in ('correlation','apply'):
        ax=figure.add_subplot(111)
        point=points[-1] if points else report.get('current_point')
        histogram(ax,point,c,phase_unit,mask_phase)
        figure.tight_layout();return dict(map=None,phase_map=None)
    gs=figure.add_gridspec(3,2,height_ratios=[1.35,1,1.15])
    ax=figure.add_subplot(gs[0,0]);pa=figure.add_subplot(gs[0,1])
    cross=figure.add_subplot(gs[1,0]);phasecut=figure.add_subplot(gs[1,1])
    hist=figure.add_subplot(gs[2,0]);along=figure.add_subplot(gs[2,1])
    xs,ys=grid(c['left']),grid(c['right']);matrix=np.full((len(ys),len(xs)),np.nan)
    phase=np.full_like(matrix,np.nan);weak=np.full_like(matrix,np.nan)
    factor,unit=phase_scale(phase_unit)
    for p in points:
        i=int(np.argmin(abs(xs-p['left'])));j=int(np.argmin(abs(ys-p['right'])))
        matrix[j,i]=100*p['fit']['visibility'];stats=phase_statistics(p['fit'])
        if stats['phase_reliable'] or not mask_phase:phase[j,i]=factor*stats['phase']
        else:weak[j,i]=1
    dx=(xs[1]-xs[0])/2;dy=(ys[1]-ys[0])/2
    extent=(xs[0]-dx,xs[-1]+dx,ys[0]-dy,ys[-1]+dy)
    cmap=mpl.colormaps['viridis'].copy();cmap.set_bad('#a0a0a0',.12)
    image=ax.imshow(np.ma.masked_invalid(matrix),origin='lower',aspect='auto',interpolation='nearest',cmap=cmap,extent=extent)
    figure.colorbar(image,ax=ax,label='Visibility (%)',pad=.02)
    cyclic=mpl.colormaps['twilight_shifted'].copy();cyclic.set_bad('#a0a0a0',.12)
    pi=pa.imshow(np.ma.masked_invalid(phase),origin='lower',aspect='auto',interpolation='nearest',cmap=cyclic,
        vmin=-np.pi*factor,vmax=np.pi*factor,extent=extent)
    grey=mpl.colors.ListedColormap(['#808895']);grey.set_bad((0,0,0,0))
    pa.imshow(np.ma.masked_invalid(weak),origin='lower',aspect='auto',interpolation='nearest',cmap=grey,vmin=0,vmax=1,extent=extent)
    cb=figure.colorbar(pi,ax=pa,label=f'Phase ({unit})',pad=.02,ticks=np.linspace(-np.pi,np.pi,5)*factor)
    if phase_unit=='rad':cb.ax.set_yticklabels(['-π','-π/2','0','π/2','π'])
    ax.set(xlabel='L_IN (V)',ylabel='R_IN (V)',title=f"Visibility · {len(points)}/{len(xs)*len(ys)} points")
    pa.set(xlabel='L_IN (V)',ylabel='R_IN (V)',title='TRG-relative phase · grey = unresolved' if mask_phase else 'TRG-relative phase · includes low-SNR estimates')
    phasecut.set(xlabel='Normal distance d (mV)',ylabel=f'Phase ({unit})',title='Phase across the valley',ylim=(-np.pi*factor,np.pi*factor))
    phasecut.set_yticks(np.linspace(-np.pi,np.pi,5)*factor)
    if phase_unit=='rad':phasecut.set_yticklabels(['-π','-π/2','0','π/2','π'])
    valley=report.get('valley',{})
    if valley.get('valid'):
        line=np.array(valley['line']);normal=np.array(valley['normal']);ci=np.array(valley['ci95_v'])
        polygon=np.vstack((line+ci[:,None]*normal,(line-ci[:,None]*normal)[::-1]))
        for axis in (ax,pa):
            axis.fill(polygon[:,0],polygon[:,1],color='tab:orange',alpha=.2)
            axis.plot(line[:,0],line[:,1],color='tab:orange',label='Compensation line')
        slices=valley['slices']
        if slices:
            ax.errorbar([s['left'] for s in slices],[s['right'] for s in slices],
                yerr=[s['right_se'] for s in slices],fmt='.',color='white',ecolor='white',label='Slice minima ±1 SE')
        distance=np.array(valley['distance_mv']);v=np.array([p['fit']['visibility'] for p in points])*100
        cross.scatter(distance,v,s=9,alpha=.4)
        d=np.linspace(distance.min(),distance.max(),200)
        cross.plot(d,100*np.sqrt(valley['floor']**2+(valley['slope_per_mv']*d)**2),color='tab:orange')
        for pos,p in zip(distance,points):
            stats=phase_statistics(p['fit'])
            if stats['phase_reliable'] or not mask_phase:
                phase_bars(phasecut,pos,stats['phase'],stats['phase_se'],factor,'tab:blue' if stats['phase_reliable'] else '#808895')
        if slices:
            center=np.array(valley['center']);tangent=np.array([-normal[1],normal[0]])
            positions=(np.array([[s['left'],s['right']] for s in slices])-center)@tangent*1000
            along.errorbar(positions,[s['floor']*100 for s in slices],yerr=[s.get('floor_se',0)*100 for s in slices],fmt='.',label='Slice fits ±1 SE')
        along.axhline(valley['floor']*100,color='tab:orange',label='Global valley floor');along.legend(fontsize=7)
        ax.legend(loc='best',fontsize=7)
    else:
        cross.text(.5,.5,valley.get('reason','Awaiting scan'),ha='center',va='center',wrap=True,transform=cross.transAxes)
    cross.set(xlabel='Normal distance d (mV)',ylabel='Visibility (%)',title='Across the valley')
    along.set(xlabel='Along-valley position s (mV)',ylabel='Residual visibility (%)',title='Along the valley')
    if candidate is not None:
        for axis in (ax,pa):axis.plot(*candidate,marker='D',color='tab:red',ms=6)
    index=selected if selected is not None and 0<=selected<len(points) else len(points)-1
    point=points[index] if points else None
    if point:
        for axis in (ax,pa):axis.plot(point['left'],point['right'],'o',mfc='none',mec='white',ms=8)
        if valley.get('valid'):
            stats=phase_statistics(point['fit']);d=valley['distance_mv'][index]
            cross.plot(d,point['fit']['visibility']*100,'o',mfc='none',mec='tab:orange',ms=8)
            if stats['phase_reliable'] or not mask_phase:phasecut.plot(d,stats['phase']*factor,'o',mfc='none',mec='tab:orange',ms=8)
    histogram(hist,point,c,phase_unit,mask_phase)
    figure.tight_layout(pad=1.4)
    return dict(map=ax,phase_map=pa,phase_values=phase,weak_values=weak,phase_cut=phasecut)


def histogram(ax,point,c,phase_unit='deg',mask_phase=True):
    ax.set(xlabel='Photon - RF arrival time (ns)',ylabel='Events',title='Selected RF-photon histogram')
    if not point or not point.get('histogram'):return
    h=np.array(point['histogram']);t=np.arange(len(h))*1.25
    ax.bar(t,h,width=1.15,alpha=.6,label='Received histogram')
    fit=point.get('fit')
    if fit:
        A,B,C=fit['coefficients'];ts=np.linspace(0,max(t),300);theta=2*np.pi*c['rf_mhz']*ts/1000
        ax.plot(ts,C+A*np.cos(theta)+B*np.sin(theta),color='tab:orange',label='RF-frequency fit')
        title=f"Visibility {100*fit['visibility']:.2f} ± {100*fit['visibility_se']:.2f}% (1 SE)\n"+phase_text(fit,phase_unit,mask_phase)
        if point.get('left') is not None:title+=f"\nL {point['left']:.5f} / R {point['right']:.5f} V"
        ax.set_title(title,fontsize=8)
    ax.legend(fontsize=7)
