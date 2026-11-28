"""Live comparisons of individual Rabi detectors and their paired sum."""
from labremote.experiments.characterization.rabi import model as rabi
from labremote.experiments.detector_comparison import comparison_roles, comparison_counts, COLORS
from labremote.experiments.characterization.shared.live_pulse import LiveSummary as ChannelSummary, LivePlot as SinglePlot


class LiveSummary:
    def __init__(self,settings):
        self.channels={role:ChannelSummary('rabi',settings) for role in comparison_roles(settings)}
        self.threshold=settings['N_threshold']

    def add(self,record):
        counts=comparison_counts(record['counts'])
        channels={role:summary.add(dict(record,counts=counts[role])) for role,summary in self.channels.items()}
        if any(value is None for value in channels.values()):return None
        if len(channels)==1:return channels['PMT']
        return dict(kind='rabi',revision=channels['PMT']['revision'],detectors=channels,threshold=self.threshold)


class LivePlot:
    def __init__(self,figure,data):
        self.single=None;self.channels={}
        if 'detectors' not in data:
            self.single=SinglePlot(figure,'rabi');return
        figure.clear();self.hist,self.axis=figure.subplots(2,1)
        for role in data['detectors']:
            label=rabi.detector_label(role);color=COLORS[role]
            histogram,=self.hist.step(range(41),[0]*41,where='mid',color=color,label=label)
            line,=self.axis.plot([],[],'o-',color=color,label=label,markersize=3)
            self.channels[role]=(histogram,line)
        self.hist.set(xlabel='Photon counts (40 includes overflow)',ylabel='Shots',ylim=(0,1))
        if data.get('threshold') is not None:
            self.hist.axvline(data['threshold'],color='0.4',ls='--',label='Shared threshold')
        self.axis.set(xlabel='Nominal microwave pulse time (us)',ylabel='Bright population',ylim=(-.05,1.05))
        self.axis.grid(True,alpha=.3);self.hist.legend(fontsize=8);self.axis.legend(fontsize=8)
        figure.tight_layout()

    def update(self,data):
        if self.single is not None:return self.single.update(data)
        maximum=1
        for role,(histogram,line) in self.channels.items():
            channel=data['detectors'][role]
            histogram.set_ydata(channel['histogram'])
            maximum=max(maximum,max(channel['histogram'])*1.2)
            if channel['points']:line.set_data(*zip(*channel['points']))
        self.hist.set_ylim(0,maximum)
        self.axis.relim();self.axis.autoscale_view(scalex=True,scaley=False)
