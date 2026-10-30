from labremote.runtime.io import Context


def set_channel_display(p, channel, enabled):
    if channel not in ('CH1','CH2','CH3','CH4'):
        raise ValueError('Select scope channel CH1..CH4')
    ctx = Context()
    ctx.assign(getattr(p, channel.lower()+'_display'),enabled)
