"""SPAM overlays: two physical PMTs and their shot-paired sum."""
import math
from labremote.experiments.detector_comparison import comparison_roles, comparison_counts, LABELS, COLORS, histogram_steps
from labremote.experiments.characterization.shared.live_pulse import LiveSummary as ChannelSummary, LivePlot as ChannelPlot


def display_data(data):
    from labremote.experiments.characterization.shared.pulse_model import detector_data
    def channel(value):
        return dict(states=value['states'],threshold=value['threshold'],
                    errors=[s['spam_error'] for s in value['states']]+[value['average_spam_error']])
    if 'detectors' not in data:return channel(data)
    return dict(detectors={role:channel(value) for role,value in detector_data(data).items()})


class LiveSummary:
    def __init__(self,settings):
        self.channels={role:ChannelSummary('spam',settings) for role in comparison_roles(settings)}

    def add(self,record):
        counts=comparison_counts(record['counts'])
        channels={role:summary.add(dict(record,counts=counts[role])) for role,summary in self.channels.items()}
        if any(value is None for value in channels.values()):return None
        if len(channels)==1:return channels['PMT']
        return dict(kind='spam',revision=channels['PMT']['revision'],detectors=channels)


class HistogramComparison:
    """State 0/1 panels share detector colors in live, final and 2D detail views."""
    def __init__(self,axes,roles):
        self.axes=axes;self.lines={};self.thresholds=[]
        from matplotlib.ticker import MaxNLocator
        for condition,ax in enumerate(axes):
            ax.set(title='No MW / target 0' if condition==0 else 'Pi pulse / target 1',
                   xlabel='Photon counts / shot',ylabel='Shots (log)',yscale='log',ylim=(.5,10))
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            for role in roles:
                self.lines[condition,role],=ax.step([],[],where='mid',color=COLORS[role],label=LABELS[role],lw=1.6)
            self.thresholds.append(ax.axvline(0,color='0.4',ls='--',label='Shared threshold'))
            ax.legend(fontsize=7);ax.grid(True,alpha=.2)

    def update(self,channels):
        for condition,ax in enumerate(self.axes):
            maximum=10;right=10
            for role,channel in channels.items():
                if 'condition' in channel['states'][0]:
                    state=next(s for s in channel['states'] if s['condition']==condition)
                else:state=channel['states'][condition]
                histogram=state['histogram']
                x,y=histogram_steps(range(len(histogram)),histogram)
                self.lines[condition,role].set_data(x,y)
                maximum=max(maximum,max(y,default=0)*2);right=max(right,max(x,default=0))
            threshold=next(iter(channels.values()))['threshold']
            self.thresholds[condition].set_xdata([threshold,threshold])
            ax.set_xlim(-.75,max(right,threshold)+.75);ax.set_ylim(.5,maximum)


def draw_histograms(figure,channels):
    figure.clear();axes=figure.subplots(1,2,squeeze=False)[0]
    plot=HistogramComparison(axes,channels);plot.update(channels)
    figure.subplots_adjust(left=.10,right=.98,bottom=.22,top=.86,wspace=.32)
    return plot


class LivePlot:
    def __init__(self,figure,data):
        self.single=None
        if 'detectors' not in data:
            self.single=ChannelPlot(figure,'spam');return
        figure.clear();grid=figure.add_gridspec(2,2)
        axes=[figure.add_subplot(grid[0,i]) for i in range(2)]
        self.histograms=HistogramComparison(axes,data['detectors'])
        self.error_axis=figure.add_subplot(grid[1,:]);self.bars={};self.labels={}
        count=len(data['detectors']);width=.8/count
        for i,role in enumerate(data['detectors']):
            positions=[j+(i-(count-1)/2)*width for j in range(3)]
            self.bars[role]=self.error_axis.bar(positions,[0]*3,width=width,color=COLORS[role],label=LABELS[role])
            self.labels[role]=[self.error_axis.text(x,0,'',ha='center',va='bottom',fontsize=8) for x in positions]
        self.error_axis.set(xticks=[0,1,2],xticklabels=['0 read as 1','1 read as 0','Equal-weight mean'],ylabel='SPAM error')
        from matplotlib.ticker import PercentFormatter
        self.error_axis.yaxis.set_major_formatter(PercentFormatter(1))
        self.error_axis.grid(axis='y',alpha=.2);self.error_axis.legend(fontsize=8)
        figure.subplots_adjust(left=.10,right=.98,bottom=.09,top=.94,hspace=.50,wspace=.30)

    def update(self,data):
        if self.single is not None:return self.single.update(data)
        channels=data['detectors'];self.histograms.update(channels);maximum=.01
        for role,channel in channels.items():
            for bar,label,value in zip(self.bars[role],self.labels[role],channel['errors']):
                bar.set_height(value if value is not None else math.nan)
                label.set_y(value or 0);label.set_text('N/A' if value is None else f'{value:.2%}')
                if value is not None:maximum=max(maximum,value)
        self.error_axis.set_ylim(0,maximum*1.25)
