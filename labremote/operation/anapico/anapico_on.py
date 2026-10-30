from labremote.runtime.io import Context


def anapico_on(p):
    ctx = Context()
    if ctx.acquire(p.output) is True:
        return True
    ctx.assign(p.output, True)
    return True
