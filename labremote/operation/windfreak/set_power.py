"""Always ramp power; this operation owns the step calculation and sequencing."""
from math import ceil, sqrt, log10
from labremote.runtime.io import Context
from labremote.runtime.bindings import bound_operation


@bound_operation(family='windfreak', parameters={'power':'power_dbm'})
def set_power(*, power, target_dbm, config):
    ctx = Context()
    current = ctx.acquire(power)
    # Sine-wave Vpp across a 50-ohm load: Vpp² = 0.4 × 10^(dBm/10).
    steps = max(1, ceil(sqrt(0.4) * abs(10 ** (target_dbm / 20) -
                                      10 ** (current / 20)) / config.max_step_vpp))
    for index in range(1, steps + 1):
        point = (target_dbm if index == steps else
                 current + 20 * log10(1 + (10 ** ((target_dbm - current) / 20) - 1) * index / steps))
        ctx.assign(power, point)
        ctx.wait(config.interval)
