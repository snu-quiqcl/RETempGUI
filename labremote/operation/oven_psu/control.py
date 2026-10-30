import time
from labremote.runtime.io import Context

OFF_CURRENT_TIMEOUT_S = 5.


def off(p):
    """Global output OFF, then verify deenergized before routing relays."""
    ctx = Context()
    ctx.assign(p.output_enabled, 'OFF')
    deadline = time.monotonic() + OFF_CURRENT_TIMEOUT_S
    while True:
        currents = [ctx.acquire(getattr(p, f'ch{ch}_measured_current')) for ch in (1, 2, 3)]
        if all(abs(value) <= .02 for value in currents):
            return {'output': 'OFF', 'currents': currents}
        if time.monotonic() >= deadline:
            raise RuntimeError('PSU OFF but measured current is not below 20 mA; relay switching blocked')
        ctx.wait(.1)


def configure(p, voltage, current):
    ctx = Context()
    if ctx.acquire(p.output_enabled) != 'OFF':
        raise RuntimeError('Turn global PSU output OFF before setting oven current')
    ctx.assign(p.tracking_enabled, 'OFF')
    # OUTP ON enables ALL outputs. Keep unused outputs at zero.
    for ch in (2, 3):
        ctx.assign(getattr(p, f'ch{ch}_current'), 0.)
        ctx.assign(getattr(p, f'ch{ch}_voltage'), 0.)
    ctx.assign(p.ch1_current, current)
    ctx.assign(p.ch1_voltage, voltage)
    return {'voltage_limit_v': voltage, 'current_limit_a': current}


def on(p, voltage, current):
    ctx = Context()
    if ctx.acquire(p.output_enabled) != 'OFF' or ctx.acquire(p.tracking_enabled) != 'OFF':
        raise RuntimeError('Unexpected PSU output/tracking state before oven ON')
    for ch in (2, 3):
        if abs(ctx.acquire(getattr(p, f'ch{ch}_voltage'))) > .01 or abs(ctx.acquire(getattr(p, f'ch{ch}_current'))) > .001:
            raise RuntimeError('Unused PSU output setpoints must be zero')
    if abs(ctx.acquire(p.ch1_voltage)-voltage) > .01 or abs(ctx.acquire(p.ch1_current)-current) > .001:
        raise RuntimeError('CH1 setpoints changed before oven ON')
    ctx.assign(p.output_enabled, 'ON')


def read_snapshot(p):
    ctx = Context()
    return {'voltage_v': ctx.acquire(p.ch1_measured_voltage),
            'current_a': ctx.acquire(p.ch1_measured_current),
            'output': ctx.acquire(p.output_enabled)}
