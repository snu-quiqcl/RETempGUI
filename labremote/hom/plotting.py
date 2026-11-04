"""Live probability displays, without fits or analysis controls."""
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
        self.batches.append(dict(batch=b['batch'],block=b['block'],a=int(sum(a)),c=int(sum(c)),total=int(sum(a)+sum(c)),coincidences=sum(b['hom']),trials=n,missing_sync=b['missing_sync'],elapsed_s=b['elapsed_s']))

    def data(self):
        n=self.trials; count=int(sum(self.h)); ref=self.ref/n if n else self.ref
        ph=count/n if n else None; pr=float(sum(ref)) if n else None
        return dict(a=self.a.tolist(),c=self.c.tolist(),hom=self.h.tolist(),reference_probability=ref.tolist(),trials=n,missing_sync=self.missing,batches=self.batches.copy(),latest=self.latest,
            metrics=dict(p_pmta=int(sum(self.a))/n if n else None,p_pmtc=int(sum(self.c))/n if n else None,p_decay_total=int(sum(self.a)+sum(self.c))/n if n else None,
            p_hom=ph,p_reference=pr,hom_reference_ratio=ph/pr if pr else None,
            expected_trials_per_coincidence=1/ph if ph else None,
            estimated_seconds_per_coincidence=sum(b['elapsed_s'] for b in self.batches)/count if count else None))


class HOMPlot:
    def __init__(self,figure,c):
        self.figure=figure; self.m=c['MAX_TIME_DIFFERENCE']; figure.clear()
        gs=figure.add_gridspec(3,2,height_ratios=[1.25,1, .85])
        self.axes=[figure.add_subplot(gs[0,:]),figure.add_subplot(gs[1,0]),figure.add_subplot(gs[1,1]),figure.add_subplot(gs[2,:])]
        figure.subplots_adjust(left=.09,right=.98,bottom=.08,top=.95,hspace=.62,wspace=.3)

    def update(self,d):
        for ax in self.axes:ax.clear(); ax.grid(alpha=.2)
        x=(np.arange(2*self.m)-self.m)*1.25; n=d['trials']; ax=self.axes[0]
        ax.step(x,np.asarray(d['hom'])/n if n else np.zeros(2*self.m),where='mid',label='HOM measured',color='#176eb5')
        ax.plot(x,d['reference_probability'],'--',label='Distinguishable reference',color='#e68a2e')
        ax.axvline(0,color='gray',lw=.7); ax.set(title='Coincidence probability per valid trial / bin',xlabel='PMTC - PMTA (ns)',ylabel='Probability / bin'); ax.set_ylim(bottom=0); ax.legend(fontsize=8)
        last=d.get('latest') or dict(a=[0]*self.m,c=[0]*self.m)
        for ax,src,title in zip(self.axes[1:3],(d,last),('Accumulated decay','Latest batch decay')):
            a=np.asarray(src['a']); c=np.asarray(src['c'])
            for values,label,color in ((a,'PMTA','#176eb5'),(c,'PMTC','#e68a2e'),(a+c,'Total','#319270')):
                ax.step(np.arange(self.m)*1.25,np.where(values>0,values,np.nan),where='mid',label=label,color=color)
            ax.set_yscale('log'); ax.set_ylim(bottom=.8,top=max(10,int(max(a+c,default=0))*1.5))
            ax.set(title=title,xlabel='PMT - SYNC (ns)',ylabel='Counts (log)'); ax.legend(fontsize=8)
        ax=self.axes[3]; b=d['batches']; x=[v['batch']+1 for v in b]
        for k,label,color in (('a','PMTA','#176eb5'),('c','PMTC','#e68a2e'),('total','Total','#319270')):
            ax.plot(x,[v[k] for v in b],'.-',label=label,color=color,ms=3)
        ax.set(title='Integrated decay counts per batch',xlabel='Batch',ylabel='Counts'); ax.set_ylim(bottom=0); ax.legend(fontsize=8)
