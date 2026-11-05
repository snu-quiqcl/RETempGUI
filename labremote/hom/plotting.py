"""Live HOM probabilities and automatic decay-tail fits."""
from labremote.decay.plotting import fit_decay
import numpy as np


class Accumulator:
    def __init__(self,c):
        self.m=c['MAX_TIME_DIFFERENCE']; self.a=np.zeros(self.m,dtype=np.int64)
        self.c=self.a.copy(); self.h=np.zeros(2*self.m,dtype=np.int64)
        self.ref=np.zeros(2*self.m); self.trials=0; self.missing=0; self.batches=[]
        self.latest=None

    def add(self,b):
        n=b['trials']; a=np.asarray(b['a']); c=np.asarray(b['c'])
        # Expected counts for each batch, then divide by total valid trials.
        ref=np.zeros(2*self.m); ref[1:]=np.correlate(c/n,a/n,'full')*.5
        self.ref+=ref*n; self.a+=a; self.c+=c; self.h+=b['hom']
        self.trials+=n; self.missing+=b['missing_sync']; self.latest=b
        self.batches.append(dict(batch=b['batch'],a=int(sum(a)),c=int(sum(c)),total=int(sum(a)+sum(c)),coincidences=sum(b['hom']),trials=n,missing_sync=b['missing_sync'],elapsed_s=b['elapsed_s']))

    def data(self):
        n=self.trials; count=int(sum(self.h)); ref=self.ref/n if n else self.ref
        ph=count/n if n else None; pr=float(sum(ref)) if n else None
        return dict(a=self.a.tolist(),c=self.c.tolist(),hom=self.h.tolist(),reference_probability=ref.tolist(),trials=n,missing_sync=self.missing,batches=self.batches.copy(),latest=self.latest,
            metrics=dict(p_pmta=int(sum(self.a))/n if n else None,p_pmtc=int(sum(self.c))/n if n else None,p_decay_total=int(sum(self.a)+sum(self.c))/n if n else None,
            p_hom=ph,p_reference=pr,total_visibility=1-ph/pr if pr else None))


class HOMPlot:
    def __init__(self,figure,c):
        self.figure=figure; self.config=c; self.m=c['MAX_TIME_DIFFERENCE']; self.fits={}; figure.clear()
        gs=figure.add_gridspec(3,2,height_ratios=[1.25,1, .85])
        self.axes=[figure.add_subplot(gs[0,:]),figure.add_subplot(gs[1,0]),figure.add_subplot(gs[1,1]),figure.add_subplot(gs[2,:])]
        self.probability_axis=self.axes[3].twinx()
        figure.subplots_adjust(left=.09,right=.88,bottom=.08,top=.95,hspace=.62,wspace=.3)

    def update(self,d):
        for ax in self.axes:ax.clear(); ax.grid(alpha=.2)
        self.probability_axis.clear(); self.probability_axis.yaxis.set_label_position('right'); self.probability_axis.yaxis.tick_right(); self.fits={}
        x=(np.arange(2*self.m)-self.m)*1.25; n=d['trials']; ax=self.axes[0]
        ax.step(x,np.asarray(d['hom'])/n if n else np.zeros(2*self.m),where='mid',label='HOM measured',color='#176eb5')
        ax.plot(x,d['reference_probability'],'--',label='Distinguishable reference',color='#e68a2e')
        ax.axvline(0,color='gray',lw=.7); ax.set(title='Coincidence probability per valid trial / bin',xlabel='PMTC - PMTA (ns)',ylabel='Probability / bin'); ax.set_ylim(bottom=0); ax.legend(fontsize=8)
        last=d.get('latest') or dict(a=[0]*self.m,c=[0]*self.m)
        for ax,src,title in zip(self.axes[1:3],(d,last),('Accumulated decay','Latest batch decay')):
            a=np.asarray(src['a']); c=np.asarray(src['c'])
            t=np.arange(self.m)*1.25; fits={}
            for values,label,color,lower in ((a,'PMTA','#176eb5',self.config['THRESHOLD_A']),(c,'PMTC','#e68a2e',self.config['THRESHOLD_C']),(a+c,'Total','#319270',max(self.config['THRESHOLD_A'],self.config['THRESHOLD_C']))):
                start=lower+int(np.argmax(values[lower:]))
                fit=fit_decay(t[start:],values[start:]); fit['start_bin']=start; fits[label]=fit
                note=f"{label}: tau={fit['tau_ns']:.2f} ns" if fit['status']=='completed' else label+': fit unavailable'
                ax.step(t,np.where(values>0,values,np.nan),where='mid',label=note,color=color)
                if fit['status']=='completed':
                    xx=np.linspace(t[start],t[-1],250)
                    yy=fit['amplitude']*np.exp(-(xx-fit['t0_ns'])/fit['tau_ns'])+fit['background']
                    ax.plot(xx,yy,'--',color=color,lw=1.6)
            self.fits['accumulated' if src is d else 'latest_batch']=fits
            ax.set_yscale('log'); ax.set_ylim(bottom=.8,top=max(10,int(max(a+c,default=0))*1.5))
            ax.set(title=title+' (dashed: fit)',xlabel='PMT - SYNC (ns)',ylabel='Counts (log)'); ax.legend(fontsize=8)
        ax=self.axes[3]; b=d['batches']; x=[v['batch']+1 for v in b]
        for k,label,color in (('a','PMTA','#176eb5'),('c','PMTC','#e68a2e'),('total','Total','#319270')):
            ax.plot(x,[v[k] for v in b],'.-',label=label,color=color,ms=3)
            self.probability_axis.plot(x,[100*v[k]/v['trials'] if v['trials'] else np.nan for v in b],':',color=color,lw=1.6)
        ax.set(title='Integrated decay counts per batch',xlabel='Batch',ylabel='Counts'); ax.set_ylim(bottom=0); ax.legend(fontsize=8)

        self.probability_axis.set_ylabel('Counts / SYNC trials (%) - dotted')
        self.probability_axis.set_ylim(bottom=0)
        return self.fits
