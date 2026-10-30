from labremote.runtime.io import Context


def set_frequency(p, value):
    ctx = Context()
    return ctx.assign(p.frequency, value)
