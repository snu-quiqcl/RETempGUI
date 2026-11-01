import numpy as np

class DecayPlot:
    def __init__(self,figure,c):
        figure.clear();self.c=c;self.axes=figure.subplots(2,2).ravel();self.lines=[];self.refs=[];self.hist=[];self.latest=[]
        channels=2 if c['mode'].endswith('dual') else 1;t=np.arange(c['MAX_TIME_DIFFERENCE'])*1.25
        for i in range(channels):
            label=c['roles']['PMT'+str(i+1)]
            self.lines.append(self.axes[0].plot(t,np.zeros(len(t)),'o-',ms=3,label=label)[0])
            self.refs.append(self.axes[0].plot([],[],'--',label=f'{label}: {c["reference_tau_ns"]} ns reference')[0])
            self.hist.append(self.axes[1].plot([],[],'o-',ms=3,label=label)[0])
            self.latest.append(self.axes[2].plot(t,np.zeros(len(t)),'o-',ms=3,label=label)[0])
        self.prompt,=self.axes[3].plot([],[],'o-',ms=3,label='Combined PMTs')
        for ax in self.axes:ax.grid(True,alpha=.3);ax.legend(fontsize=8)
        self.axes[0].set(title='Accumulated decay',xlabel='PMT - SYNC (ns)',ylabel='Counts')
        self.axes[1].set(title='Decay counts per batch (last may be partial)',xlabel='PC batch',ylabel='Counts')
        self.axes[2].set(title='Latest completed hardware chunk',xlabel='PMT - SYNC (ns)',ylabel='Counts')
        self.axes[3].set(title='Accumulated prompt window',xlabel='PMT - SYNC (ns)',ylabel='Counts')
        if c['SIGNAL_THRESHOLD']==c['DECAY_THRESHOLD']:self.axes[3].text(.5,.5,'No prompt window configured',transform=self.axes[3].transAxes,ha='center')
        for ax in (self.axes[0],self.axes[2]):ax.axvline(c['DECAY_THRESHOLD']*1.25,color='gray',ls='--')
        figure.subplots_adjust(left=.09,right=.98,bottom=.1,top=.93,wspace=.3,hspace=.4)

    def update(self,data):
        c=self.c;start=c['DECAY_THRESHOLD'];lower=c['SIGNAL_THRESHOLD'];t=np.arange(c['MAX_TIME_DIFFERENCE'])*1.25
        for i,(line,reference,history,latest) in enumerate(zip(self.lines,self.refs,self.hist,self.latest)):
            counts=np.asarray(data['counts'][i]);line.set_ydata(counts)
            reference.set_data(t[start:],counts[start]*np.exp(-(t[start:]-t[start])/c['reference_tau_ns']))
            history.set_data([b['batch'] for b in data['batches']],[b['decay_counts'][i] for b in data['batches']])
            latest.set_ydata(data['latest'][i])
        prompt=np.sum(np.asarray(data['counts']),axis=0);self.prompt.set_data(t[lower:start],prompt[lower:start])
        for ax in self.axes:
            ax.relim();ax.autoscale_view();ax.set_ylim(bottom=0)

class Accumulator:
    def __init__(self,c):
        self.c=c;self.channels=2 if c['mode'].endswith('dual') else 1
        self.counts=np.zeros((self.channels,c['MAX_TIME_DIFFERENCE']),dtype=np.int64);self.latest=self.counts.copy();self.batches={};self.trials=0;self.chunks=0
    def add(self,chunk):
        hist=np.asarray(chunk['histograms'],dtype=np.int64);self.counts+=hist;self.latest=hist;self.trials+=chunk['trials'];self.chunks+=1
        b=self.batches.setdefault(chunk['batch'],dict(batch=chunk['batch'],trials=0,complete=False,decay_counts=[0]*self.channels,prompt_counts=0,elapsed_s=0.))
        b['trials']+=chunk['trials'];b['complete']=chunk['batch_complete'];b['elapsed_s']+=chunk['elapsed_s']
        for i in range(self.channels):b['decay_counts'][i]+=int(hist[i,self.c['DECAY_THRESHOLD']:].sum())
        b['prompt_counts']+=int(hist[:,self.c['SIGNAL_THRESHOLD']:self.c['DECAY_THRESHOLD']].sum())
    def data(self):
        from copy import deepcopy
        return dict(counts=self.counts.tolist(),latest=self.latest.tolist(),batches=deepcopy(list(self.batches.values())),trials=self.trials,chunks=self.chunks)
