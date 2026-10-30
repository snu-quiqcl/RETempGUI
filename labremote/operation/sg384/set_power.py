"""Always ramp power; this operation owns the step calculation and sequencing."""
from math import ceil, sqrt, log10, isfinite
from labremote.runtime.io import Context


def set_power(*, power, target_dbm, config, unit='dBm'):
    if unit == 'Vpp':
        # Convert the input representation only. Each ramp assign enforces limits.
        if isinstance(target_dbm,bool) or not isinstance(target_dbm,(int,float)) or not isfinite(target_dbm) or target_dbm<=0:
            raise ValueError('Vpp must be a finite positive number')
        target_dbm=10*log10(((target_dbm/(2*sqrt(2)))**2/50)/.001)
    elif unit != 'dBm':
        raise ValueError('Power unit must be dBm or Vpp')
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
