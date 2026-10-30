from labremote.runtime.io import Context


def set_channel_display(p, channel, enabled):
    if channel not in ('CH1','CH2'):
        raise ValueError('Select scope channel CH1 or CH2')
    ctx = Context()
    ctx.assign(getattr(p, channel.lower()+'_display'),
               'ON' if enabled is True else 'OFF' if enabled is False else enabled)
