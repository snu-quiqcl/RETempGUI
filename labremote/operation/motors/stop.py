from labremote.runtime.io import Context

def stop(p):
    ctx=Context()
    ctx.assign(p.stop_request,True)
    return ctx.acquire(p.status)
