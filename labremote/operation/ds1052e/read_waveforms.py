from labremote.runtime.io import Context
import numpy as np


def read_waveforms(p, channels=('CH1','CH2')):
    channels=(channels,) if isinstance(channels,str) else tuple(channels)
    if not channels or len(channels)>2 or any(ch not in ('CH1','CH2') for ch in channels) or len(set(channels))!=len(channels):
        raise ValueError('Select CH1 and/or CH2 without duplicates')
    ctx = Context()
    ctx.assign(p.waveform_mode, 'NORM')
    time_scale = ctx.acquire(p.time_scale)
    time_offset = ctx.acquire(p.time_offset)
    result = dict(traces={}, scales={}, timebase=dict(scale=time_scale,offset=time_offset))
    for channel in channels:
        prefix = channel.lower()+'_'
        if ctx.acquire(getattr(p,prefix+'display')) != 'ON':
            continue
        scale = ctx.acquire(getattr(p,prefix+'scale'))
        offset = ctx.acquire(getattr(p,prefix+'offset'))
        samples = ctx.acquire(getattr(p,prefix+'waveform'))
        raw = np.frombuffer(samples,dtype=np.uint8).astype(np.float64)
        times = np.arange(raw.size)*(time_scale/50)-6*time_scale+time_offset
        volts = (240-raw)*(scale/25)-(offset+scale*4.6)
        result['traces'][channel] = (times,volts)
        result['scales'][channel] = dict(vdiv=scale,offset=offset)
    return result
