from labremote.runtime.io import Context

def measure(p, channel, exposure_ms):
    ctx=Context()
    ctx.assign(p.channel,channel)
    ctx.assign(p.exposure_ms,exposure_ms)
    return ctx.acquire(p.measurement)
