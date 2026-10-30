from labremote.runtime.io import Context


def configure_vertical(p, channel, scale_vdiv, offset_v):
    if channel not in ('CH1','CH2','CH3','CH4'):
        raise ValueError('Select scope channel CH1..CH4')
    ctx = Context()
    ctx.assign(getattr(p, channel.lower()+'_scale'), scale_vdiv)
    ctx.assign(getattr(p, channel.lower()+'_offset'), offset_v)
