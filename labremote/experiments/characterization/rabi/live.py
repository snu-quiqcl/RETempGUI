"""Independent Rabi display channels sharing one threshold and pulse sweep."""
from labremote.experiments.characterization.rabi import model as rabi
from labremote.experiments.characterization.shared.live_pulse import LiveSummary as ChannelSummary, LivePlot as SinglePlot


class LiveSummary:
    def __init__(self,settings):
        self.channels={role:ChannelSummary('rabi',settings) for role in rabi.detector_roles(settings)}

    def add(self,record):
        counts=rabi.counts_by_detector(record['counts'])
        channels={role:summary.add(dict(record,counts=counts[role])) for role,summary in self.channels.items()}
        if any(value is None for value in channels.values()):return None
        if len(channels)==1:return channels['PMT']
        return dict(kind='rabi',revision=channels['PMT']['revision'],detectors=channels)


class LivePlot:
    def __init__(self,figure,data):
        self.single=None;self.channels={}
        if 'detectors' not in data:
            self.single=SinglePlot(figure,'rabi');return
        figure.clear();axes=figure.subplots(2,2,squeeze=False)
        for column,role in enumerate(('PMT','PMT2')):
            hist,axis=axes[:,column];color='C'+str(column)
            bars=hist.bar(range(41),[0]*41,color=color)
            hist.set(title=rabi.detector_label(role),xlabel='Photon counts (40 includes overflow)',ylabel='Counts',ylim=(0,1))
            line,=axis.plot([],[],'o-',color=color)
            axis.set(xlabel='Nominal microwave pulse time (us)',ylabel='Bright population',ylim=(-.05,1.05))
            axis.grid(True,alpha=.3)
            self.channels[role]=(hist,bars,axis,line)
        figure.tight_layout()

    def update(self,data):
        if self.single is not None:return self.single.update(data)
        for role,(hist,bars,axis,line) in self.channels.items():
            channel=data['detectors'][role]
            for bar,value in zip(bars,channel['histogram']):bar.set_height(value)
            hist.set_ylim(0,max(1,max(channel['histogram'])*1.2))
            line.set_data(*zip(*channel['points']));axis.relim();axis.autoscale_view(scalex=True,scaley=False)
