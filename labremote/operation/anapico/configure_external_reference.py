"""Apply reference settings; lock is observed separately by acquire/monitor."""
from labremote.runtime.io import Context


def configure_external_reference(p, hz):
    ctx = Context()
    ctx.assign(p.external_lock_frequency, hz)
    ctx.assign(p.reference_source, 'EXT')
