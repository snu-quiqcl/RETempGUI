from labremote.runtime.io import Context


def set_vva(p, channel, value):
    ctx = Context()
    return ctx.assign(getattr(p, f"ch{channel}").vva_level, value)
