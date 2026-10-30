from labremote.runtime.io import Context


def read_reference_events(p):
    ctx = Context()
    return ctx.acquire(p.reference_events)
