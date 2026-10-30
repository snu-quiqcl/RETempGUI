from labremote.runtime.io import Context


def set_reference_output(p, hz, enabled):
    ctx = Context()
    ctx.assign(p.reference_output_frequency, hz)
    return ctx.assign(p.reference_output_enabled, enabled)
