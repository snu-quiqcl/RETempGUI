from labremote.runtime.io import Context


def read_snapshot(p):
    ctx = Context()
    values = {}
    for path in ('status_json', 'ch1.frequency_hz', 'ch1.phase_deg', 'ch1.vva_level', 'ch1.output_enabled', 'ch2.frequency_hz', 'ch2.phase_deg', 'ch2.vva_level', 'ch2.output_enabled', 'ch3.frequency_hz', 'ch3.phase_deg', 'ch3.vva_level', 'ch3.output_enabled', 'ch4.frequency_hz', 'ch4.phase_deg', 'ch4.vva_level', 'ch4.output_enabled'):
        parameter = p
        for part in path.split("."): parameter = getattr(parameter, part)
        values[path] = ctx.acquire(parameter)
    return values
