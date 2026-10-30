from labremote.runtime.io import Context


def set_frequency(p, channel, value):
    ctx = Context()
    return ctx.assign(getattr(p, f"ch{channel}").frequency_hz, value)
