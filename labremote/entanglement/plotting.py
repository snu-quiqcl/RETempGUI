"""Decay fitting, herald probability and censored attempt statistics."""
from copy import deepcopy
import numpy as np
from labremote.decay.plotting import fit_decay

COLORS = ('#176eb5', '#e68a2e', '#319270')

def decay_fits(data, c):
    result = {}
    for values, label, lower in ((data['a'],'PMTA',c['decay_lower_a']),
            (data['c'],'PMTC',c['decay_lower_c']),
            (np.asarray(data['a'])+data['c'],'Total',max(c['decay_lower_a'],c['decay_lower_c']))):
        values = np.asarray(values)
        start = lower + int(np.argmax(values[lower:]))
        fit = fit_decay(np.arange(start,120)*1.25,values[start:])
        result[label] = dict(fit,start_bin=start)
    return result

def decay_counts(data, c):
    a=int(sum(data['a'][c['decay_lower_a']:]))
    b=int(sum(data['c'][c['decay_lower_c']:]))
    return dict(a=a,c=b,total=a+b)

class Accumulator:
    def __init__(self, c):
        self.config=c; self.a=np.zeros(120,dtype=np.int64); self.c=self.a.copy()
        self.coincidence=np.zeros(240,dtype=np.int64); self.attempts=0; self.heralds=0
        self.states=[0]*4; self.batches=[]; self.latest=None; self.elapsed=0.

    def add(self, b):
        self.a+=b['a']; self.c+=b['c']; self.coincidence+=b['coincidence']
        self.attempts+=b['attempts']; self.heralds+=int(b['heralded']); self.elapsed+=b['elapsed_s']
        if b['heralded']:self.states[int(b['state_label'],2)]+=1
        self.latest=deepcopy(b)
        counts=decay_counts(b,self.config)
        self.batches.append(dict(batch=b['batch'],attempts=b['attempts'],heralded=b['heralded'],
            **counts,elapsed_s=b['elapsed_s']))

    def data(self):
        n=self.attempts
        counts=decay_counts(dict(a=self.a,c=self.c),self.config); a=counts['a']; c=counts['c']
        return dict(a=self.a.tolist(),c=self.c.tolist(),coincidence=self.coincidence.tolist(),
            attempts=n,heralds=self.heralds,states=self.states.copy(),batches=deepcopy(self.batches),latest=deepcopy(self.latest),
            metrics=dict(p_herald=self.heralds/n if n else None,p_pmta=a/n if n else None,
                p_pmtc=c/n if n else None,decay_counts_per_attempt=(a+c)/n if n else None,
                decay_countrate=(a+c)/self.elapsed if self.elapsed else None,
                exhausted_batches=len(self.batches)-self.heralds))

def geometric_bins(data, max_attempts):
    edges=np.unique(np.ceil(np.geomspace(1,max_attempts+1,31))).astype(np.int64)
    if len(edges)<2:edges=np.array([1,2])
    successes=[b['attempts'] for b in data['batches'] if b['heralded']]
    observed=np.histogram(successes,bins=edges)[0]/max(1,len(data['batches']))
    p=data['metrics']['p_herald'] or 0.
    expected=np.power(1-p,edges[:-1]-1)-np.power(1-p,edges[1:]-1)
    return edges,observed,expected

class EntanglementPlot:
    def __init__(self, figure, c):
        self.figure=figure; self.config=c; figure.clear()
        self.axes=figure.subplots(3,2).ravel(); self.probability_axis=self.axes[3].twinx()
        self.fits={}
        figure.subplots_adjust(left=.08,right=.9,bottom=.07,top=.94,hspace=.62,wspace=.38)

    def update(self, d):
        for ax in self.axes:ax.clear(); ax.grid(alpha=.18)
        self.probability_axis.clear()
        last=d.get('latest') or dict(a=[0]*120,c=[0]*120)
        for ax,src,title,key in zip(self.axes[:2],(d,last),('Accumulated arrivals','Latest batch arrivals'),('accumulated','latest_batch')):
            fits=decay_fits(src,self.config); self.fits[key]=fits
            for values,name,color in zip((src['a'],src['c'],np.asarray(src['a'])+src['c']),('PMTA','PMTC','Total'),COLORS):
                values=np.asarray(values); f=fits[name]; label=name
                if f['status']=='completed':label+=f": tau={f['tau_ns']:.2f} ns"
                ax.step(np.arange(120)*1.25,np.where(values>0,values,np.nan),where='mid',color=color,label=label)
                if f['status']=='completed':
                    x=np.linspace(f['t0_ns'],148.75,200)
                    ax.plot(x,f['amplitude']*np.exp(-(x-f['t0_ns'])/f['tau_ns'])+f['background'],'--',color=color)
            for lower in sorted(set((self.config['decay_lower_a'],self.config['decay_lower_c']))):
                ax.axvline(lower*1.25,color='gray',ls=':',lw=.8)
            ax.set_xlim(0,148.75)
            ax.set_yscale('log'); ax.set_ylim(.8,max(10,max(np.asarray(src['a'])+src['c'])*1.5))
            ax.set(title=title+' (dashed: decay fit)',xlabel='PMT - SYNC (ns); dotted: cutoffs',ylabel='Counts / bin (log)')
            ax.legend(fontsize=8)
        ax=self.axes[2]; x=(np.arange(240)-120)*1.25; w=self.config['coincidence_half_window_bins']*1.25
        ax.step(x,d['coincidence'],where='mid',color='#7565b8',label='Received coincidences')
        ax.axvspan(-w,w,alpha=.12,color='#319270',label='Herald window [lower, upper)')
        ax.set(title='Coincidence time differences',xlabel='PMTC - PMTA (ns)',ylabel='Counts / bin'); ax.set_ylim(bottom=0); ax.legend(fontsize=8)
        ax=self.axes[3]; batches=d['batches']; x=[b['batch']+1 for b in batches]
        for key,name,color in zip(('a','c','total'),('PMTA','PMTC','Total'),COLORS):
            ax.plot(x,[b[key] for b in batches],'.-',ms=3,color=color,label=name)
            self.probability_axis.plot(x,[100*b[key]/b['attempts'] for b in batches],':',color=color)
        ax.set(title='Decay counts per batch (after cutoffs)',xlabel='Batch',ylabel='Counts'); ax.set_ylim(bottom=0); ax.legend(fontsize=8)
        self.probability_axis.set_ylabel('Counts / attempts (%) · dotted'); self.probability_axis.set_ylim(bottom=0)
        self.probability_axis.yaxis.set_label_position('right'); self.probability_axis.yaxis.tick_right()
        ax=self.axes[4]
        from .config import nominal_trials
        edges,observed,expected=geometric_bins(d,nominal_trials(self.config))
        ax.bar(edges[:-1],observed,width=np.diff(edges),align='edge',alpha=.45,color=COLORS[0],label='Observed / completed batches')
        ax.plot(np.sqrt(edges[:-1].astype(float))*np.sqrt(edges[1:].astype(float)),expected,'.-',color=COLORS[1],label='Geometric model (same bins)')
        ax.set_xscale('log'); ax.set_xlim(1,edges[-1]); ax.set_ylim(bottom=0)
        ax.set(title='Attempts to herald · logarithmic bins',xlabel='Attempt N (log)',ylabel='Probability / log bin'); ax.legend(fontsize=7)
        ax.text(.98,.96,f"Exhausted: {d['metrics']['exhausted_batches']}",ha='right',va='top',transform=ax.transAxes,fontsize=8)
        ax=self.axes[5]; values=np.array(d['states'])/max(1,d['heralds'])
        ax.bar(['00','01','10','11'],values,color=['#9aaabd',COLORS[0],COLORS[2],'#9aaabd'])
        for i,(n,p) in enumerate(zip(d['states'],values)):ax.text(i,p+.025,f'{n} ({p:.1%})',ha='center',fontsize=8)
        ax.set_ylim(0,1.15); ax.set(title='State readout · '+self.config['basis'],xlabel='EA, EC (bright = 1)',ylabel='Probability / heralded batch')
        return self.fits
