from labremote.runtime.io import Context

def close(p):
    ctx=Context()
    ctx.assign(p.close_request,True)
    return ctx.acquire(p.status)
