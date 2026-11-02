from labremote.runtime.io import Context


def configure_impedance(p, channel, impedance):
    if channel not in ('CH1', 'CH2', 'CH3', 'CH4'):
        raise ValueError('Select scope channel CH1..CH4')
    if impedance not in ('OMEG', 'FIFT'):
        raise ValueError('Select OMEG (1 Mohm) or FIFT (50 ohm)')
    ctx = Context()
    ctx.assign(getattr(p, channel.lower() + '_impedance'), impedance)
    # The instrument can change its vertical range when termination changes.
    for field in ('scale', 'offset'):
        ctx.acquire(getattr(p, channel.lower() + '_' + field))
