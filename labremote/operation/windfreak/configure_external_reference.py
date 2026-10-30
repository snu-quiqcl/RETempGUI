from labremote.runtime.bindings import bound_operation
from labremote.runtime.io import Context


@bound_operation(family='windfreak', trees=('p',))
def configure_external_reference(p, hz):
    ctx = Context()
    ctx.assign(p.reference_mode, 'external')
    ctx.assign(p.reference_frequency_hz, hz)
