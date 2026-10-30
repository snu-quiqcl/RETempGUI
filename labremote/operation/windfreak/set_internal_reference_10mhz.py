from labremote.runtime.bindings import bound_operation
from labremote.runtime.io import Context


@bound_operation(family='windfreak', trees=('p',))
def set_internal_reference_10mhz(p):
    ctx = Context()
    ctx.assign(p.reference_mode, 'internal 10mhz')
