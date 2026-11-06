"""Shared live/export figures. Heatmap axes always L_IN (x), R_IN (y)."""
import numpy as np
from .config import grid


def draw(figure,report,selected=None,candidate=None):
    figure.clear()
    c=report['settings'];points=report.get('points',[]);mode=report.get('mode','scan')
    if mode=='input':
        ax=figure.add_subplot(111);d=report.get('rf_test')
        if d:
            ax.plot(np.arange(len(d['counts'])),d['counts'],'.-',label='Received counts')
            ax.axhline(d['expected'],color='tab:orange',label='Expected');ax.legend()
            ax.set_title(f"RF input: mean {d['mean']:.2f}, std {d['std']:.2f}")
        ax.set(xlabel='Gate index',ylabel='RF counts');figure.tight_layout();return dict(map=None)
    if mode in ('correlation','apply'):
        ax=figure.add_subplot(111)
        point=points[-1] if points else report.get('current_point')
        histogram(ax,point,c);figure.tight_layout();return dict(map=None)
    gs=figure.add_gridspec(3,2,height_ratios=[1.6,1,1.15])
    ax=figure.add_subplot(gs[0,:]);cross=figure.add_subplot(gs[1,0]);along=figure.add_subplot(gs[1,1]);hist=figure.add_subplot(gs[2,:])
    xs,ys=grid(c['left']),grid(c['right']);matrix=np.full((len(ys),len(xs)),np.nan)
    for p in points:
        i=int(np.argmin(abs(xs-p['left'])));j=int(np.argmin(abs(ys-p['right'])))
        matrix[j,i]=100*p['fit']['visibility']
    dx=(xs[1]-xs[0])/2;dy=(ys[1]-ys[0])/2
    cmap=__import__('matplotlib').colormaps['viridis'].copy();cmap.set_bad('#a0a0a0',.15)
    image=ax.imshow(np.ma.masked_invalid(matrix),origin='lower',aspect='auto',interpolation='nearest',cmap=cmap,
        extent=(xs[0]-dx,xs[-1]+dx,ys[0]-dy,ys[-1]+dy))
    figure.colorbar(image,ax=ax,label='Visibility (%)',pad=.02)
    ax.set(xlabel='L_IN (V)',ylabel='R_IN (V)',title=f"RF-photon visibility · {len(points)}/{len(xs)*len(ys)} points")
    valley=report.get('valley',{})
    if valley.get('valid'):
        line=np.array(valley['line']);normal=np.array(valley['normal']);ci=np.array(valley['ci95_v'])
        plus=line+ci[:,None]*normal;minus=line-ci[:,None]*normal
        polygon=np.vstack((plus,minus[::-1]))
        ax.fill(polygon[:,0],polygon[:,1],color='tab:orange',alpha=.25,label='95% local CI')
        ax.plot(line[:,0],line[:,1],color='tab:orange',label='Compensation line')
        slices=valley['slices']
        if slices:
            ax.errorbar([s['left'] for s in slices],[s['right'] for s in slices],
                yerr=[s['right_se'] for s in slices],fmt='.',color='white',ecolor='white',label='Slice minima ±1 SE')
        distance=np.array(valley['distance_mv']);v=np.array([p['fit']['visibility'] for p in points])*100
        cross.scatter(distance,v,s=9,alpha=.4)
        d=np.linspace(distance.min(),distance.max(),200)
        cross.plot(d,100*np.sqrt(valley['floor']**2+(valley['slope_per_mv']*d)**2),color='tab:orange')
        if slices:
            center=np.array(valley['center']);tangent=np.array([-normal[1],normal[0]])
            positions=(np.array([[s['left'],s['right']] for s in slices])-center)@tangent*1000
            along.errorbar(positions,[s['floor']*100 for s in slices],
                yerr=[s.get('floor_se',0)*100 for s in slices],fmt='.',label='Slice fits ±1 SE')
        along.axhline(valley['floor']*100,color='tab:orange',label='Global valley floor');along.legend(fontsize=8)
        ax.legend(loc='best',fontsize=8)
    else:
        cross.text(.5,.5,valley.get('reason','Awaiting scan'),ha='center',va='center',wrap=True,transform=cross.transAxes)
    cross.set(xlabel='Normal distance d (mV)',ylabel='Visibility (%)',title='Across the valley')
    along.set(xlabel='Along-valley position s (mV)',ylabel='Residual visibility (%)',title='Along the valley')
    if candidate is not None:ax.plot(*candidate,marker='D',color='tab:red',ms=7)
    point=points[selected] if selected is not None and 0<=selected<len(points) else points[-1] if points else None
    if point:
        ax.plot(point['left'],point['right'],'o',mfc='none',mec='white',ms=9)
    histogram(hist,point,c)
    figure.tight_layout(pad=1.5)
    return dict(map=ax)


def histogram(ax,point,c):
    ax.set(xlabel='Photon - RF arrival time (ns)',ylabel='Events',title='Selected RF-photon histogram')
    if not point or not point.get('histogram'):return
    h=np.array(point['histogram']);t=np.arange(len(h))*1.25
    ax.bar(t,h,width=1.15,alpha=.6,label='Received histogram')
    fit=point.get('fit')
    if fit:
        A,B,C=fit['coefficients'];ts=np.linspace(0,max(t),300);theta=2*np.pi*c['rf_mhz']*ts/1000
        ax.plot(ts,C+A*np.cos(theta)+B*np.sin(theta),color='tab:orange',label='RF-frequency fit')
        title=f"Visibility {100*fit['visibility']:.2f} ± {100*fit['visibility_se']:.2f}% (1 SE)"
        title+=f" · phase {fit['phase']:.3f} rad" if fit['phase_reliable'] else ' · phase not resolved'
        if point.get('left') is not None:title+=f" · L {point['left']:.5f} / R {point['right']:.5f} V"
        ax.set_title(title,fontsize=10)
    ax.legend(fontsize=8)
