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
            hist,passed,error=figure.subplots(3,1)
            self.lines=[hist.plot(range(40),[math.nan]*40,drawstyle='steps-mid',label=label)[0] for label in ('No MW pulse / target 0','π pulse / target 1')]
            hist.set(xlabel='Photon counts (39 includes overflow)',ylabel='Final detections',yscale='log',ylim=(.8,10));hist.legend()
            self.hist=hist;self.passed=passed.bar([0,1],[0,0]);self.errors=error.bar([0,1,2],[0,0,0])
            passed.set(xticks=[0,1],xticklabels=['Target 0','Target 1'],ylabel='Successes / attempts',ylim=(0,1.18))
            error.set(xticks=[0,1,2],xticklabels=['0 read as 1','1 read as 0','Equal-weight mean'],ylabel='Conditional SPAM error',ylim=(0,1.18))
            self.labels=[error.text(i,0,'N/A',ha='center',va='bottom') for i in range(3)]
            from matplotlib.ticker import PercentFormatter
            for ax in (passed,error):ax.yaxis.set_major_formatter(PercentFormatter(1));ax.grid(True,axis='y',alpha=.3)
        else:
            hist,ax=figure.subplots(2,1);self.hist=hist;self.bars=hist.bar(range(41),[0]*41)
            hist.set(xlabel='Photon counts (40 includes overflow)',ylabel='Occurrences',ylim=(0,1))
            self.line,=ax.plot([],[],'o-');self.axis=ax
            ax.set(xlabel='Nominal free precession time (ms)' if kind=='ramsey' else 'Nominal initialization time (us)',ylabel='Bright population',ylim=(-.05,1.05));ax.grid(True,alpha=.3)
        figure.subplots_adjust(left=.12,right=.97,bottom=.09,top=.96,hspace=.45)

    def update(self,data):
        if self.kind=='spam':
            for line,state,bar in zip(self.lines,data['states'],self.passed):
                line.set_ydata([v if v else math.nan for v in state['histogram']])
                bar.set_height(state['successes']/state['attempts'] if state['attempts'] else math.nan)
            self.hist.set_ylim(.8,max(10,max(max(s['histogram']) for s in data['states'])*1.3))
            for bar,label,value in zip(self.errors,self.labels,data['errors']):
                bar.set_height(value if value is not None else math.nan);label.set_y(value or 0);label.set_text('N/A' if value is None else f'{value:.3%}')
        else:
            for bar,value in zip(self.bars,data['histogram']):bar.set_height(value)
            self.hist.set_ylim(0,max(1,max(data['histogram'])*1.2))
            self.line.set_data(*zip(*data['points']));self.axis.relim();self.axis.autoscale_view(scalex=True,scaley=False)
