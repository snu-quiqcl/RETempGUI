from labremote.runtime.io import Context


def anapico_off(p):
    ctx = Context()
    if ctx.acquire(p.output) is False:
        return False
    ctx.assign(p.output, False)
    return False
