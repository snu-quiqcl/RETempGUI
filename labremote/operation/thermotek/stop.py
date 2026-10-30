from labremote.runtime.io import Context


def stop(p):
    ctx=Context()
    ctx.assign(p.run_request,False)
    return ctx.acquire(p.watchdog_json)
