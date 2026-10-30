from labremote.runtime.io import Context


def configure_horizontal(p, time_scale_s, time_offset_s):
    ctx = Context()
    ctx.assign(p.time_scale, time_scale_s)
    ctx.assign(p.time_offset, time_offset_s)
