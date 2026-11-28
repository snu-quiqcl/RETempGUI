"""Decay fitting, herald probability and censored attempt statistics."""
from copy import deepcopy
from collections import Counter
from labremote.experiments.detector_comparison import COLORS as PMT_COLORS, LABELS as PMT_LABELS, histogram_steps
import numpy as np
from labremote.experiments.decay.plotting import fit_decay
from functools import lru_cache

@lru_cache(maxsize=256)
def _cached_fit(values,lower):
    values=np.asarray(values)
    start=lower+int(np.argmax(values[lower:]))
    return dict(fit_decay(np.arange(start,120)*1.25,values[start:]),start_bin=start)

COLORS = ('#176eb5', '#e68a2e', '#319270')

def decay_fits(data, c):
    result = {}
    for values, label, lower in ((data['a'],'PMTA',c['decay_lower_a']),
            (data['c'],'PMTC',c['decay_lower_c']),
            (np.asarray(data['a'])+data['c'],'Total',max(c['decay_lower_a'],c['decay_lower_c']))):
        values = np.asarray(values)
        result[label] = deepcopy(_cached_fit(tuple(values.tolist()),lower))
    return result

def decay_counts(data, c):
    a=int(sum(data['a'][c['decay_lower_a']:]))
    b=int(sum(data['c'][c['decay_lower_c']:]))
    return dict(a=a,c=b,total=a+b)

def decay_reference(data, c):
    """Pooled decay estimate, same 1/2 distinguishable factor as HOM."""
    n=data['attempts']
    a=np.asarray(data['a'],dtype=float).copy(); b=np.asarray(data['c'],dtype=float).copy()
    a[:c['decay_lower_a']]=0; b[:c['decay_lower_c']]=0
    probability=None
    if n:
        reference=np.zeros(240)
        reference[1:]=.5*np.correlate(b/n,a/n,'full')
        w=c['coincidence_half_window_bins']
        probability=float(reference[120-w:120+w].sum())
    return dict(model='distinguishable_50_50_equal_contributions',
        formula='p_ref = 0.5 * sum(p_A[i] * p_C[j] for -w <= j-i < w); mean_trials = 1/p_ref',
        normalization='Pooled cutoff-filtered arrival counts / actual trials; independent-emission reference, no HOM suppression; untruncated geometric mean',
        actual_trials=n, coincidence_half_window_bins=c['coincidence_half_window_bins'],
        probability_per_trial=probability,
        mean_trials=1/probability if probability else None)

class Accumulator:
    def __init__(self, c):
        self.config=c; self.a=np.zeros(120,dtype=np.int64); self.c=self.a.copy()
        self.coincidence=np.zeros(240,dtype=np.int64); self.attempts=0; self.heralds=0
        self.readout_counts={'ea':Counter(),'ec':Counter()}
        self.readout_individual={ion:{role:Counter() for role in ('PMT1','PMT2')} for ion in ('ea','ec')}
        self.states=[0]*4; self.batches=[]; self.latest=None; self.elapsed=0.

    def add(self, b):
        self.a+=b['a']; self.c+=b['c']; self.coincidence+=b['coincidence']
        self.attempts+=b['attempts']; self.heralds+=int(b['heralded']); self.elapsed+=b['elapsed_s']
        if b['heralded']:
            self.states[int(b['state_label'],2)]+=1
            for ion in ('ea','ec'):
                self.readout_counts[ion][int(b['state_counts'][ion])]+=1
                for role,value in b.get('state_counts_by_pmt',{}).get(ion,{}).items():
                    self.readout_individual[ion][role][int(value)]+=1
        self.latest=deepcopy(b)
        counts=decay_counts(b,self.config)
        self.batches.append(dict(batch=b['batch'],attempts=b['attempts'],heralded=b['heralded'],
            **counts,elapsed_s=b['elapsed_s']))

    def readout_histograms(self):
        result={}
        for ion,counts in self.readout_counts.items():
            threshold=self.config['threshold_'+ion]
            values=sorted(counts); total=sum(counts.values())
            dark=sum(n for value,n in counts.items() if value<=threshold)
            result[ion]=dict(photon_counts=values,frequencies=[counts[v] for v in values],
                bin_width_counts=1,unlisted_bins_frequency=0,threshold=threshold,
                bright_rule='counts > threshold',readouts=total,dark=dark,bright=total-dark,
                detection_us=self.config['detection_'+ion+'_us'] if self.config.get('experiment')=='entanglement_no_mirror' else self.config['detection_us'])
        return result

    def individual_histograms(self):
        return {ion:{role:dict(photon_counts=sorted(counts),frequencies=[counts[v] for v in sorted(counts)],readouts=sum(counts.values()))
                     for role,counts in detectors.items()} for ion,detectors in self.readout_individual.items()}

    def data(self):
        n=self.attempts
        counts=decay_counts(dict(a=self.a,c=self.c),self.config); a=counts['a']; c=counts['c']
        return dict(a=self.a.tolist(),c=self.c.tolist(),coincidence=self.coincidence.tolist(),
            state_readout_histograms=self.readout_histograms(),
            **(dict(state_readout_histograms_by_pmt=self.individual_histograms()) if self.config.get('experiment')=='entanglement_no_mirror' else {}),
            attempts=n,heralds=self.heralds,states=self.states.copy(),batches=deepcopy(self.batches),latest=deepcopy(self.latest),
            decay_reference=decay_reference(dict(a=self.a,c=self.c,attempts=n),self.config),
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
    def __init__(self, figure, c, reuse_artists=False):
        self.figure=figure; self.config=c; figure.clear()
        self.axes=figure.subplots(4,2).ravel(); self.probability_axis=self.axes[3].twinx()
        self.fits={};self.reuse_artists=reuse_artists;self.artists={};self.used=set();self.legends={};self.initialized=False
        figure.subplots_adjust(left=.08,right=.9,bottom=.10 if c.get('experiment')=='entanglement_no_mirror' else .055,top=.94,hspace=.62,wspace=.38)

    def line(self,ax,key,x,y,**kwargs):
        if not self.reuse_artists:return ax.plot(x,y,**kwargs)
        identity=(ax,key);self.used.add(identity)
        line=self.artists.get(identity)
        if line is None:
            line,=ax.plot(x,y,**kwargs);self.artists[identity]=line
        else:
            line.set_data(x,y);line.set(**kwargs);line.set_visible(True)
        return [line]

    def text(self,ax,key,x,y,text,**kwargs):
        if not self.reuse_artists:return ax.text(x,y,text,**kwargs)
        identity=(ax,key);self.used.add(identity);artist=self.artists.get(identity)
        if artist is None:
            artist=ax.text(x,y,text,**kwargs);self.artists[identity]=artist
        else:artist.set_text(text);artist.set_position((x,y));artist.set_visible(True)
        return artist

    def bars(self,ax,key,x,y,width,**kwargs):
        if not self.reuse_artists:return ax.bar(x,y,width=width,**kwargs)
        identity=(ax,key);self.used.add(identity);bars=self.artists.get(identity)
        if bars is None or len(bars)!=len(x):
            if bars is not None:bars.remove()
            bars=ax.bar(x,y,width=width,**kwargs);self.artists[identity]=bars
        else:
            widths=np.broadcast_to(width,len(x));colors=kwargs.get('color')
            for i,(patch,xx,yy,ww) in enumerate(zip(bars,x,y,widths)):
                patch.set_x(xx if kwargs.get('align')=='edge' else xx-ww/2)
                patch.set_height(yy);patch.set_width(ww)
                if colors is not None:patch.set_facecolor(colors if isinstance(colors,str) else colors[i])
        return bars

    def legend(self,ax,**kwargs):
        handles,labels=ax.get_legend_handles_labels()
        pairs=[(h,label) for h,label in zip(handles,labels) if not hasattr(h,'get_visible') or h.get_visible()]
        labels=tuple(label for h,label in pairs)
        if not self.reuse_artists or self.legends.get(ax)!=labels:
            ax.legend([h for h,label in pairs],labels,**kwargs);self.legends[ax]=labels

    def rescale(self,ax):
        if self.reuse_artists:
            ax.relim(visible_only=True);ax.autoscale(enable=True,axis='both')

    def update(self, d, prepared_fits=None):
        self.used=set()
        for artist in self.artists.values():
            if hasattr(artist,'set_visible'):artist.set_visible(False)
        if not self.reuse_artists or not self.initialized:
            for ax in self.axes:ax.clear();ax.grid(alpha=.18)
            self.probability_axis.clear()
        else:
            # Four population bars include changing errorbars; only this small axis rebuilds.
            self.axes[5].clear();self.axes[5].grid(alpha=.18)
        last=d.get('latest') or dict(a=[0]*120,c=[0]*120)
        for ax,src,title,key in zip(self.axes[:2],(d,last),('Accumulated arrivals','Latest batch arrivals'),('accumulated','latest_batch')):
            fits=prepared_fits[key] if prepared_fits is not None else decay_fits(src,self.config); self.fits[key]=fits
            for values,name,color in zip((src['a'],src['c'],np.asarray(src['a'])+src['c']),('PMTA','PMTC','Total'),COLORS):
                values=np.asarray(values); f=fits[name]; label=name
                if f['status']=='completed':label+=f": tau={f['tau_ns']:.2f} ns"
                self.line(ax,name,np.arange(120)*1.25,np.where(values>0,values,np.nan),drawstyle='steps-mid',color=color,label=label)
                if f['status']=='completed':
                    x=np.linspace(f['t0_ns'],148.75,200)
                    self.line(ax,name+' fit',x,f['amplitude']*np.exp(-(x-f['t0_ns'])/f['tau_ns'])+f['background'],ls='--',color=color)
            for lower in sorted(set((self.config['decay_lower_a'],self.config['decay_lower_c']))):
                self.line(ax,('cutoff',lower),[lower*1.25]*2,[0,1],transform=ax.get_xaxis_transform(),color='gray',ls=':',lw=.8)
            first_bin=max(0,min(self.config['decay_lower_a'],self.config['decay_lower_c'])-5)
            ax.set_xlim(first_bin*1.25,148.75)
            ax.set_yscale('log'); ax.set_ylim(.8,max(10,max((np.asarray(src['a'])+src['c'])[first_bin:])*1.5))
            ax.set(title=title+' (dashed: decay fit)',xlabel='PMT - SYNC (ns); dotted: cutoffs',ylabel='Counts / bin (log)')
            self.legend(ax,fontsize=8)
        ax=self.axes[2]; x=(np.arange(240)-120)*1.25; w=self.config['coincidence_half_window_bins']*1.25
        self.line(ax,'coincidence',x,d['coincidence'],drawstyle='steps-mid',color='#7565b8',label='Received coincidences')
        if not self.reuse_artists or not self.initialized:ax.axvspan(-w,w,alpha=.12,color='#319270',label='Herald window [lower, upper)')
        self.rescale(ax)
        ax.set(title='Coincidence time differences',xlabel='PMTC - PMTA (ns)',ylabel='Counts / bin'); ax.set_ylim(bottom=0); self.legend(ax,fontsize=8)
        ax=self.axes[3]; batches=d['batches']; x=[b['batch']+1 for b in batches]
        for key,name,color in zip(('a','c','total'),('PMTA','PMTC','Total'),COLORS):
            rates=[b[key]/b['attempts'] if b['attempts'] else np.nan for b in batches]
            self.line(ax,name,x,rates,marker='.',ls='-',ms=3,color=color,label=name)
        self.rescale(ax)
        ax.set(title='Decay per actual trial by batch (after cutoffs)',xlabel='Batch',ylabel='Counts / actual trial'); ax.set_ylim(bottom=0); self.legend(ax,fontsize=8)
        self.probability_axis.set_ylabel('Counts / actual trial (%)')
        self.probability_axis.set_ylim(*(100*v for v in ax.get_ylim()))
        self.probability_axis.yaxis.set_label_position('right'); self.probability_axis.yaxis.tick_right()
        ax=self.axes[4]
        from labremote.experiments.entanglement.config import nominal_trials
        edges,observed,expected=geometric_bins(d,nominal_trials(self.config))
        self.bars(ax,'observed',edges[:-1],observed,width=np.diff(edges),align='edge',alpha=.45,color=COLORS[0],label='Observed / completed batches')
        self.line(ax,'model',np.sqrt(edges[:-1].astype(float))*np.sqrt(edges[1:].astype(float)),expected,marker='.',ls='-',color=COLORS[1],label='Geometric model (same bins)')
        reference=d.get('decay_reference') or decay_reference(d,self.config)
        mean=reference['mean_trials']
        if mean is not None:
            self.line(ax,'reference',[mean]*2,[0,1],transform=ax.get_xaxis_transform(),color='#cf4747',ls='--',lw=1.5,
                label=f'Decay reference mean: {mean:,.3g} trials')
        else:
            self.text(ax,'unavailable',.02,.96,'Decay reference mean: unavailable',va='top',transform=ax.transAxes,fontsize=7)
        self.rescale(ax)
        ax.set_xscale('log'); ax.set_xlim(1,max(float(edges[-1]),mean*1.15 if mean is not None else 1)); ax.set_ylim(bottom=0)
        ax.set(title='Attempts to herald · logarithmic bins',xlabel='Attempt N (log)',ylabel='Probability / log bin'); self.legend(ax,fontsize=7)
        self.text(ax,'exhausted',.98,.96,f"Exhausted: {d['metrics']['exhausted_batches']}",ha='right',va='top',transform=ax.transAxes,fontsize=8)
        ax=self.axes[5]; values=np.array(d['states'])/max(1,d['heralds'])
        errors=np.sqrt(values*(1-values)/max(1,d['heralds']))
        ax.bar(['00','01','10','11'],values,yerr=errors if d['heralds'] else None,capsize=4,color=['#9aaabd',COLORS[0],COLORS[2],'#9aaabd'])
        for i,(n,p) in enumerate(zip(d['states'],values)):ax.text(i,p+errors[i]+.025,f'{n} ({p:.1%})',ha='center',fontsize=8)
        ax.set_ylim(0,1.15); ax.set(title='Population · '+self.config['basis']+' (±1σ binomial)' ,xlabel='EA, EC (bright = 1)',ylabel='Probability / heralded batch')
        from matplotlib.ticker import MaxNLocator
        for ax,ion in zip(self.axes[6:],('ea','ec')):
            hist=d['state_readout_histograms'][ion]
            threshold=hist['threshold']; n=hist['readouts']
            x=np.asarray(hist['photon_counts'],dtype=int)
            colors=np.where(x<=threshold,'#7594b6','#df983d')
            comparison=self.config.get('experiment')=='entanglement_no_mirror'
            maximum=max(hist['frequencies'],default=0);right=int(x.max())+1 if len(x) else 0
            if comparison:
                channels=d.get('state_readout_histograms_by_pmt',{}).get(ion,{})
                for role,key in (('PMT','PMT1'),('PMT2','PMT2'),('SUM',None)):
                    channel=hist if key is None else channels.get(key)
                    if channel is None:continue
                    xx,yy=histogram_steps(channel['photon_counts'],channel['frequencies'])
                    self.line(ax,role,xx,yy,drawstyle='steps-mid',color=PMT_COLORS[role],lw=1.6,label=PMT_LABELS[role])
                    maximum=max(maximum,max(yy,default=0));right=max(right,max(xx,default=0))
            else:self.bars(ax,'readout',x,hist['frequencies'],width=.88,color=colors,zorder=3)
            self.line(ax,'threshold',[threshold+.5]*2,[0,1],transform=ax.get_xaxis_transform(),color='#c34747',ls='--',lw=1.5,
                label=f'Sum > {threshold}: bright' if comparison else f'Threshold: counts > {threshold} is bright')
            if n:
                text=f"0 / dark: {hist['dark']} ({hist['dark']/n:.1%})\n1 / bright: {hist['bright']} ({hist['bright']/n:.1%})"
            else:text='No completed state readouts'
            self.text(ax,'readout summary',.97,.95,text,ha='right',va='top',transform=ax.transAxes,fontsize=8,
                bbox=dict(facecolor='white',alpha=.85,edgecolor='none'))
            ax.set(title=ion.upper()+' state readout histogram',xlabel='Photon counts / detection (state from sum)' if comparison else 'Readout photon counts / detection',ylabel='Number of readouts')
            ax.set_xlim(-.65,max(10,threshold+2,right))
            ax.set_ylim(0,max(1,maximum*1.25))
            ax.xaxis.set_major_locator(MaxNLocator(integer=True,nbins=9))
            ax.yaxis.set_major_locator(MaxNLocator(integer=True,nbins=6))
            self.legend(ax,loc='upper center',bbox_to_anchor=(.5,-.23),fontsize=7,frameon=False,ncol=2 if comparison else 1)
        for identity,artist in self.artists.items():
            if identity not in self.used and hasattr(artist,'set_visible'):artist.set_visible(False)
        self.initialized=True
        return self.fits
