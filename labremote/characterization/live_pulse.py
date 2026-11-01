"""Bounded display summaries; no fitting, hardware access, or file writes."""
import math


class LiveSummary:
    def __init__(self,kind,settings):
        self.kind=kind;self.settings=settings;self.seen=set();self.points=[]
        self.states=[dict(histogram=[0]*40,attempts=0,successes=0,received=0,bright=0,batches=0) for _ in range(2)]

    def add(self,record):
        if not record['complete'] or record['index'] in self.seen:return None
        self.seen.add(record['index']);counts=record['counts'];n=len(counts)
        bright=sum(v>=self.settings['N_threshold'] for v in counts)
        if self.kind=='spam':
            state=self.states[record['condition']]
            for v in counts:state['histogram'][min(v,39)]+=1
            state['attempts']+=record['attempts'];state['successes']+=record['successes']
            state['received']+=n;state['bright']+=bright;state['batches']+=1
            errors=[(s['bright'] if i==0 else s['received']-s['bright'])/s['received'] if s['received'] else None for i,s in enumerate(self.states)]
            data=dict(states=self.states,errors=errors+[sum(errors)/2 if all(e is not None for e in errors) else None])
        else:
            step=self.settings['precession_time']*.00001 if self.kind=='ramsey' else self.settings['T_init_step']*.01
            self.points.append([record['index']*step,bright/n if n else None])
            histogram=[0]*41
            for v in counts:histogram[min(v,40)]+=1
            data=dict(points=sorted(self.points),histogram=histogram)
        # Each queued Qt message owns a small immutable-in-practice snapshot.
        from copy import deepcopy
        return deepcopy(dict(kind=self.kind,revision=len(self.seen),**data))


class LivePlot:
    def __init__(self,figure,kind):
        self.kind=kind;figure.clear()
        if kind=='spam':
            hist,error=figure.subplots(2,1)
            self.lines=[hist.plot(range(40),[math.nan]*40,drawstyle='steps-mid',marker='o',markersize=3,label=label)[0] for label in ('No MW pulse / target 0','π pulse / target 1')]
            hist.set(xlabel='Photon counts (39 includes overflow)',ylabel='Occurrences (cumulative)',title='Population histogram',yscale='log',ylim=(.8,10));hist.legend()
            self.hist=hist;self.error_axis=error;self.errors=error.bar([0,1,2],[0,0,0])
            error.set(xticks=[0,1,2],xticklabels=['0 read as 1','1 read as 0','Equal-weight mean'],ylabel='Conditional SPAM error')
            self.labels=[error.text(i,0,'N/A',ha='center',va='bottom') for i in range(3)]
            from matplotlib.ticker import PercentFormatter
            error.yaxis.set_major_formatter(PercentFormatter(1));error.grid(True,axis='y',alpha=.3)
            hist.grid(True,which='both',alpha=.2)
        else:
            hist,ax=figure.subplots(2,1);self.hist=hist;self.bars=hist.bar(range(41),[0]*41)
            hist.set(xlabel='Photon counts (40 includes overflow)',ylabel='Occurrences',ylim=(0,1))
            self.line,=ax.plot([],[],'o-');self.axis=ax
            ax.set(xlabel='Nominal free precession time (ms)' if kind=='ramsey' else 'Nominal initialization time (us)',ylabel='Bright population',ylim=(-.05,1.05));ax.grid(True,alpha=.3)
        figure.subplots_adjust(left=.12,right=.97,bottom=.09,top=.96,hspace=.45)

    def update(self,data):
        if self.kind=='spam':
            for line,state in zip(self.lines,data['states']):
                line.set_ydata([v if v else math.nan for v in state['histogram']])
            self.hist.set_ylim(.8,max(10,max(max(s['histogram']) for s in data['states'])*1.3))
            for bar,label,value in zip(self.errors,self.labels,data['errors']):
                bar.set_height(value if value is not None else math.nan);label.set_y(value or 0);label.set_text('N/A' if value is None else f'{value:.3%}')
            finite=[v for v in data['errors'] if v is not None and math.isfinite(v)]
            low,high=(min(finite),max(finite)) if finite else (0,0)
            pad=max((high-low)*.2,high*.1,1e-4)
            bottom=max(0,low-pad);self.error_axis.set_ylim(bottom,high+pad*2)
            for label,value in zip(self.labels,data['errors']):
                if value is None:label.set_y(bottom+pad*.1)
        else:
            for bar,value in zip(self.bars,data['histogram']):bar.set_height(value)
            self.hist.set_ylim(0,max(1,max(data['histogram'])*1.2))
            self.line.set_data(*zip(*data['points']));self.axis.relim();self.axis.autoscale_view(scalex=True,scaley=False)
