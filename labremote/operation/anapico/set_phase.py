from labremote.runtime.io import Context


def set_phase(p, value):
    ctx = Context()
    return ctx.assign(p.phase, value)
