from labremote.runtime.io import Context


def set_internal_reference(p):
    ctx = Context()
    return ctx.assign(p.reference_source, 'INT')
