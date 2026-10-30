from labremote.runtime.io import Context

def set_range(p, low, high):
    ctx=Context()
    ctx.assign(p.horizontal_unit,'FREQUENCY')
    ctx.assign(p.frequency_start_thz,low)
    ctx.assign(p.frequency_stop_thz,high)
