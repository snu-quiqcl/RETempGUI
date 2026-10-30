from labremote.runtime.io import Context

def home(p):
    ctx=Context()
    ctx.assign(p.home_request,True)
    return ctx.acquire(p.status)
