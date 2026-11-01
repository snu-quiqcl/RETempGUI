"""Original PMT sample sequence and analysis, without serial ownership or GUI."""
import numpy as np
from scipy.stats import poisson
from labremote.devices.fpga.controller import hd
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram,reg


def build_program(settings,route):
    from .config import sequence_hardware
    mapped=sequence_hardware(route);s=SequencerProgram()
    s.load_immediate(reg[0],0)
    s.repeat_measurement=s.trigger_out([mapped.PMT_counter_reset])
    s.set_output_port(hd.counter_control_port,[(mapped.PMT_counter_enable,1)])
    s.load_immediate(reg[1],0)
    s.wait_exposure=s.wait_n_clocks(10000-3-2)
    s.add(reg[1],reg[1],1)
    s.branch_if_less_than('wait_exposure',reg[1],round(settings['exposure_ms']*10))
    s.set_output_port(hd.counter_control_port,[(mapped.PMT_counter_enable,0)])
    s.read_counter(reg[2],mapped.PMT_counter_result)
    s.write_to_fifo(reg[0],reg[1],reg[2],10)
    s.add(reg[0],reg[0],1)
    s.branch_if_less_than('repeat_measurement',reg[0],settings['num_average']);s.stop()
    return s


def analyze(counts,exposure_ms):
    counts=np.asarray(counts,dtype=np.int64);n=len(counts)
    if not n:raise ValueError('No valid samples to analyze')
    mean=float(counts.mean());x=np.arange(int(counts.max())+1)
    histogram=np.bincount(counts,minlength=len(x));expected=poisson.pmf(x,mean)*n
    dt=exposure_ms/1000;frequency=np.array([]);power=np.array([]);peak=None
    if n>=3:
        window=np.hanning(n);spectrum=np.fft.rfft((counts-mean)*window)
        frequency=np.fft.rfftfreq(n,d=dt)
        power=abs(spectrum)**2/((1/dt)*np.sum(window**2))
        # Match the supplied script's one-sided normalization exactly.
        power[1:-1]*=2
        if np.any(power[1:]>0):peak=float(frequency[np.argmax(power[1:])+1])
    return dict(time_ms=np.arange(n)*exposure_ms,counts=counts,histogram_x=x,histogram=histogram,poisson=expected,
                frequency_hz=frequency,power=power,summary=dict(samples=n,mean_count=mean,std_count=float(counts.std()),peak_hz=peak,
                nominal_sample_interval_ms=exposure_ms,fft_timebase='Nominal exposure spacing; inter-batch host gaps excluded'))


def draw(figure,data):
    figure.clear();axes=figure.subplots(3,1)
    axes[0].plot(data['time_ms'],data['counts'],lw=.8);axes[0].set(xlabel='Time (ms)',ylabel='PMT Counts')
    axes[1].bar(data['histogram_x'],data['histogram'],label='Measured',color='skyblue')
    axes[1].plot(data['histogram_x'],data['poisson'],'r.-',label=f"Poisson (lambda={data['summary']['mean_count']:.2f})")
    axes[1].axvline(data['summary']['mean_count'],linestyle=':',color='r')
    axes[1].set(xlabel='PMT Counts',ylabel='Occurrences');axes[1].legend()
    axes[2].plot(data['frequency_hz'],data['power']);axes[2].set(xlabel='Frequency (Hz)',ylabel='Normalized Power')
    for ax in axes:ax.grid(alpha=.3)
    figure.tight_layout()
