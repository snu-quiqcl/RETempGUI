import warnings
import numpy as np

BIN_NS = 1.25

def fit_decay(x, y):
    """Fit observed counts, not a fixed reference lifetime."""
    from scipy.optimize import curve_fit, OptimizeWarning
    x=np.asarray(x,dtype=float);y=np.asarray(y,dtype=float)
    if len(x)<5 or not np.isfinite(y).all() or np.count_nonzero(y)<4 or np.ptp(y)<=0:
        return dict(status='unavailable',reason='Insufficient decay data')
    def model(t,a,tau,b):return a*np.exp(-t/tau)+b
    z=x-x[0];upper=max(1.,float(z[-1])*100)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',OptimizeWarning)
            p,cov=curve_fit(model,z,y,p0=[max(float(np.ptp(y)),1.),max(float(z[-1])/4,BIN_NS),float(y.min())],
                bounds=([0,.01,0],[np.inf,upper,np.inf]),sigma=np.sqrt(np.maximum(y,1)),absolute_sigma=True,maxfev=2500)
        if not np.isfinite(p).all() or not np.isfinite(cov).all() or p[1]>=upper*.99:raise ValueError('Uncertain lifetime')
        return dict(status='completed',amplitude=float(p[0]),tau_ns=float(p[1]),background=float(p[2]),tau_std_ns=float(np.sqrt(max(0,cov[1,1]))),t0_ns=float(x[0]),model='A*exp(-(t-t0)/tau)+background')
    except (ValueError,RuntimeError,OptimizeWarning,FloatingPointError) as exc:
        return dict(status='unavailable',reason=str(exc))

class DecayPlot:
    def __init__(self,figure,c):
        figure.clear();self.c=c;self.axes=figure.subplots(3,2).ravel()
        self.probability_axis=self.axes[4].twinx();self.fits={};self._fit_revision=None
        self.channels=2 if c['mode'].endswith('dual') else 1
        self.labels=[c['roles']['PMT'+str(i+1)] for i in range(self.channels)]
        if self.channels==2:self.labels.append(' + '.join(self.labels))
        self.series=[[] for _ in range(6)];self.fit_lines=[];self.probability_lines=[]
        colors=('#55b9ff','#f2ae58','#63d7ac')
        for i,label in enumerate(self.labels):
            for k,axis in enumerate(self.axes):
                self.series[k].append(axis.plot([],[],'o-',ms=3,lw=1,color=colors[i],label=label)[0])
            self.fit_lines.append(self.axes[0].plot([],[],'--',lw=1.5,color=colors[i],label=label+' fit')[0])
            self.probability_lines.append(self.probability_axis.plot([],[],':',lw=1.4,color=colors[i])[0])
        titles=['1  Accumulated decay','2  Latest batch decay','3  Accumulated pulse + 5 clocks','4  Latest batch pulse + 5 clocks','5  Decay totals per batch','6  Pulse totals per batch']
        for k,axis in enumerate(self.axes):
            axis.set(title=titles[k],xlabel='PMT − SYNC (ns)' if k<4 else 'Batch',ylabel='Counts / bin' if k<4 else 'Counts')
            axis.grid(True,alpha=.25);axis.legend(fontsize=7)
        self.probability_axis.set_ylabel('Counts / trials (%) · dotted')
        start=c['DECAY_THRESHOLD']*BIN_NS;lower=c['SIGNAL_THRESHOLD']*BIN_NS
        for k in range(4):self.axes[k].axvline(start,color='gray',ls=':',lw=1)
        for k in (2,3):
            self.axes[k].axvline(lower,color='gray',ls=':',lw=1)
            self.axes[k].axvspan(start,min(start+5*BIN_NS,(c['MAX_TIME_DIFFERENCE']-1)*BIN_NS),alpha=.08,color='gray')
            if lower==start:self.axes[k].text(.03,.9,'Empty pulse window',transform=self.axes[k].transAxes,fontsize=8)
        self.fit_note=self.axes[0].text(.02,.03,'',transform=self.axes[0].transAxes,fontsize=7)
        self.batch_note=self.axes[1].text(.02,.9,'',transform=self.axes[1].transAxes,fontsize=8)
        figure.subplots_adjust(left=.09,right=.88,bottom=.08,top=.95,wspace=.48,hspace=.58)

    def _channels(self,values):
        values=np.asarray(values,dtype=float)
        return np.concatenate((values,values.sum(axis=0,keepdims=True)),axis=0) if self.channels==2 else values

    def update(self,data):
        c=self.c;start=c['DECAY_THRESHOLD'];lower=c['SIGNAL_THRESHOLD'];bins=c['MAX_TIME_DIFFERENCE']
        end=min(bins,start+6)  # Include the sample five stopwatch clocks after the boundary.
        t=np.arange(bins)*BIN_NS;counts=self._channels(data['counts']);batches=data.get('batches',[])
        last=batches[-1] if batches else None
        # Legacy last-chunk data cannot be presented as a complete batch.
        latest=self._channels(last['histograms']) if last and 'histograms' in last else np.full_like(counts,np.nan)
        self.batch_note.set_text(('Batch '+str(last['batch']+1)+(' (partial)' if not last['complete'] else '')) if last and 'histograms' in last else 'Batch histogram unavailable')
        self.axes[3].set_title('4  Latest batch pulse + 5 clocks'+(' (partial)' if last and not last['complete'] else ''))
        xs=[b['batch']+1 for b in batches]
        decay=np.asarray([b['decay_counts'] for b in batches],dtype=float).T if batches else np.empty((self.channels,0))
        prompt=np.asarray([b.get('prompt_counts_by_channel',[b['prompt_counts']] if self.channels==1 else [np.nan]*self.channels) for b in batches],dtype=float).T if batches else np.empty((self.channels,0))
        decay=self._channels(decay);prompt=self._channels(prompt)
        if self.channels==2:prompt[-1]=[b['prompt_counts'] for b in batches]
        trials=np.asarray([b['trials'] for b in batches],dtype=float)
        revision=(data.get('chunks'),float(np.sum(counts)),len(batches))
        if revision!=self._fit_revision:
            self.fits={label:fit_decay(t[start:],y[start:]) for label,y in zip(self.labels,counts)};self._fit_revision=revision
        notes=[]
        for i,label in enumerate(self.labels):
            for k,xx,yy in ((0,t[start:],counts[i,start:]),(1,t[start:],latest[i,start:]),(2,t[lower:end],counts[i,lower:end]),(3,t[lower:end],latest[i,lower:end]),(4,xs,decay[i]),(5,xs,prompt[i])):
                self.series[k][i].set_data(xx,yy)
            probability=np.divide(decay[i]*100,trials,out=np.full_like(trials,np.nan),where=trials>0)
            self.probability_lines[i].set_data(xs,probability)
            f=self.fits[label]
            if f['status']=='completed':
                xx=np.linspace(t[start],t[-1],250);yy=f['amplitude']*np.exp(-(xx-f['t0_ns'])/f['tau_ns'])+f['background']
                self.fit_lines[i].set_data(xx,yy);notes.append(f"{label}: τ={f['tau_ns']:.2f} ns")
            else:self.fit_lines[i].set_data([],[]);notes.append(label+': fit unavailable')
        self.fit_note.set_text(' | '.join(notes))
        for axis in (*self.axes,self.probability_axis):
            axis.relim();axis.autoscale_view();axis.set_ylim(bottom=0)
        for k in (0,1):self.axes[k].set_xlim(t[start]-.25,t[-1]+.25)
        for k in (2,3):self.axes[k].set_xlim(t[lower]-.25,t[end-1]+.25)
        return self.fits

class Accumulator:
    def __init__(self,c):
        self.c=c;self.channels=2 if c['mode'].endswith('dual') else 1
        self.counts=np.zeros((self.channels,c['MAX_TIME_DIFFERENCE']),dtype=np.int64);self.latest=self.counts.copy();self.batches={};self.trials=0;self.chunks=0
    def add(self,chunk):
        hist=np.asarray(chunk['histograms'],dtype=np.int64);self.counts+=hist;self.latest=hist;self.trials+=chunk['trials'];self.chunks+=1
        b=self.batches.setdefault(chunk['batch'],dict(batch=chunk['batch'],trials=0,complete=False,decay_counts=[0]*self.channels,prompt_counts=0,prompt_counts_by_channel=[0]*self.channels,histograms=np.zeros_like(hist).tolist(),elapsed_s=0.))
        b['trials']+=chunk['trials'];b['complete']=chunk['batch_complete'];b['elapsed_s']+=chunk['elapsed_s']
        b['histograms']=(np.asarray(b['histograms'],dtype=np.int64)+hist).tolist()
        for i in range(self.channels):
            b['decay_counts'][i]+=int(hist[i,self.c['DECAY_THRESHOLD']:].sum())
            b['prompt_counts_by_channel'][i]+=int(hist[i,self.c['SIGNAL_THRESHOLD']:self.c['DECAY_THRESHOLD']].sum())
        b['prompt_counts']=sum(b['prompt_counts_by_channel'])
    def data(self):
        from copy import deepcopy
        return dict(counts=self.counts.tolist(),latest=self.latest.tolist(),batches=deepcopy(list(self.batches.values())),trials=self.trials,chunks=self.chunks)
