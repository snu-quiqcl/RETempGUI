from labremote.runtime.bindings import bound_operation
from labremote.runtime.io import Context


@bound_operation(family='windfreak', trees=('p',))
def set_internal_reference_27mhz(p):
    ctx = Context()
    ctx.assign(p.reference_mode, 'internal 27mhz')
