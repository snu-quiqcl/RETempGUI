from labremote.runtime.io import Context


def read_snapshot(p):
    ctx = Context()
    values = {}
    for path in ('frequency', 'phase', 'output', 'reference_source', 'external_lock_frequency', 'locked', 'reference_output_enabled', 'reference_output_frequency'):
        values[path] = ctx.acquire(getattr(p, path))
    return values
