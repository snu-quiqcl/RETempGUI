import time
from labremote.runtime.io import Context

OFF_CURRENT_TIMEOUT_S = 5.
RAMP_STEP_A = .15
RAMP_INTERVAL_S = .4


def set_current(p, current):
    Context().assign(p.ch1_current, current)


def ramp_down(p, start_current):
    """Uncancelled cleanup operation; always attempt OFF if ramping fails."""
    ctx = Context()
    try:
        value = start_current
        while value > 0:
            value = round(max(0., value - RAMP_STEP_A), 6)
            ctx.assign(p.ch1_current, value)
            ctx.wait(RAMP_INTERVAL_S)
    finally:
        off(p)


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
    ctx.assign(p.ch1_current, 0.)
    ctx.assign(p.ch1_voltage, voltage)
    return {'voltage_limit_v': voltage, 'current_limit_a': current}


def on(p, voltage, current):
    ctx = Context()
    if ctx.acquire(p.output_enabled) != 'OFF' or ctx.acquire(p.tracking_enabled) != 'OFF':
        raise RuntimeError('Unexpected PSU output/tracking state before oven ON')
    # configure() has already written the channel limits under workflow ownership.
    # Do not query VOLT?/CURR? here: legacy loading does not use setpoint reads.
    # Successful writes are not represented as verified device settings.
    ctx.assign(p.output_enabled, 'ON')


def read_snapshot(p):
    ctx = Context()
    return {'voltage_v': ctx.acquire(p.ch1_measured_voltage),
            'current_a': ctx.acquire(p.ch1_measured_current),
            'output': ctx.acquire(p.output_enabled)}
