from labremote.runtime.io import Context


def read_snapshot(p):
    ctx = Context()
    values = {}
    for path in ('time_scale', 'time_offset', 'trigger_mode', 'trigger_status', 'trigger_source', 'trigger_level', 'trigger_slope', 'trigger_sweep', 'ch1_display', 'ch1_scale', 'ch1_offset', 'ch1_frequency', 'ch1_vpp', 'ch2_display', 'ch2_scale', 'ch2_offset', 'ch2_frequency', 'ch2_vpp'):
        values[path] = ctx.acquire(getattr(p, path))
    return values
