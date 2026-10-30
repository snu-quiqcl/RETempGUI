from labremote.runtime.io import Context

def read_spectrum(p):
    ctx=Context()
    ctx.assign(p.sweep_mode,'SINGLE')
    ctx.assign(p.clear_status,True)
    ctx.assign(p.sweep_start,True)
    ctx.assign(p.data_format,'ASCII')
    return ctx.acquire(p.spectrum)
