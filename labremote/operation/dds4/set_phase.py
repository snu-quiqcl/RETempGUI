from labremote.runtime.io import Context


def set_phase(p, channel, value):
    ctx = Context()
    return ctx.assign(getattr(p, f"ch{channel}").phase_deg, value)
