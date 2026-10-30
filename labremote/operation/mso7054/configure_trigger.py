from labremote.runtime.io import Context


def configure_trigger(p, channel, level_v, slope='POS', sweep='AUTO'):
    if channel not in ('CH1','CH2','CH3','CH4'):
        raise ValueError('Select scope channel CH1..CH4')
    ctx = Context()
    ctx.assign(p.trigger_type, 'EDGE')
    ctx.assign(p.trigger_source, 'CHAN'+channel[-1])
    ctx.assign(p.trigger_slope, slope)
    ctx.assign(p.trigger_level, level_v)
    ctx.assign(p.sweep, sweep)
