from labremote.runtime.io import Context


def read_snapshot(p):
    ctx = Context()
    values = {}
    for path in ('frequency', 'phase', 'timebase_code', 'bnc_power_dbm', 'bnc_power_vpp', 'bnc_output', 'n_power_dbm', 'n_power_vpp', 'n_output'):
        values[path] = ctx.acquire(getattr(p, path))
    return values
