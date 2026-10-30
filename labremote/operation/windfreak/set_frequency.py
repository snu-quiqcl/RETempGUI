from labremote.runtime.bindings import bound_operation
from labremote.runtime.io import Context


@bound_operation(family='windfreak', trees=('p',))
def set_frequency(p, channel, value):
    ctx = Context()
    module = getattr(p, f'channel_{channel}')
    return ctx.assign(module.frequency_hz, value)
