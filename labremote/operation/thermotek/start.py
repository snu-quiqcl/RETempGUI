from labremote.runtime.io import Context


def start(p):
    ctx=Context()
    ctx.assign(p.run_request,True)
    return ctx.acquire(p.watchdog_json)
