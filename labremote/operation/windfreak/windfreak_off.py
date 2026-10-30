"""Ramp down before disabling output; this operation owns its step sequence."""
from math import ceil, sqrt, log10


def windfreak_off(ctx, power, output, config):
    current = ctx.acquire(power)
    if current > config.low_power:
        # Sine-wave Vpp across a 50-ohm load: Vpp² = 0.4 × 10^(dBm/10).
        steps = max(1, ceil(sqrt(0.4) * abs(10 ** (config.low_power / 20) -
                                          10 ** (current / 20)) / config.max_step_vpp))
        for index in range(1, steps + 1):
            point = (config.low_power if index == steps else
                     current + 20 * log10(1 + (10 ** ((config.low_power - current) / 20) - 1) * index / steps))
            ctx.assign(power, point)
            ctx.wait(config.interval)
    ctx.assign(output, False)
    return False
