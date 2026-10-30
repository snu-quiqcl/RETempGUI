from labremote.runtime.io import Context

def open(p):
    ctx=Context()
    ctx.assign(p.open_request,True)
    return ctx.acquire(p.status)
