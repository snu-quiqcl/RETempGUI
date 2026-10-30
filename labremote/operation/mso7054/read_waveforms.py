from labremote.runtime.io import Context
import numpy as np


def read_waveforms(p, channels=('CH1','CH2','CH3','CH4')):
    channels=(channels,) if isinstance(channels,str) else tuple(channels)
    if not channels or len(channels)>4 or len(set(channels))!=len(channels) or any(ch not in ('CH1','CH2','CH3','CH4') for ch in channels):
        raise ValueError('Select distinct MSO7054 channels CH1..CH4')
    ctx=Context()
    ctx.assign(p.waveform_mode,'NORM')
    ctx.assign(p.waveform_format,'BYTE')
    ctx.assign(p.waveform_start,1)
    ctx.assign(p.waveform_stop,1000)
    result=dict(traces={},scales={},timebase=dict(scale=ctx.acquire(p.time_scale),offset=ctx.acquire(p.time_offset)))
    for channel in channels:
        prefix=channel.lower()+'_'
        if not ctx.acquire(getattr(p,prefix+'display')):continue
        scale=ctx.acquire(getattr(p,prefix+'scale'))
        offset=ctx.acquire(getattr(p,prefix+'offset'))
        ctx.assign(p.waveform_source,'CHAN'+channel[-1])
        pre=ctx.acquire(p.waveform_preamble)
        raw=np.frombuffer(ctx.acquire(p.waveform_data),dtype=np.uint8).astype(np.float64)
        times=(np.arange(raw.size)-pre[6])*pre[4]+pre[5]
        volts=(raw-pre[9]-pre[8])*pre[7]
        result['traces'][channel]=(times,volts)
        result['scales'][channel]=dict(vdiv=scale,offset=offset)
    return result
