from labremote.runtime.io import Context


def pid_step(p, axis, voltage):
    if axis not in ('X','Y','Z'):raise ValueError('Select X, Y or Z')
    Context().assign(getattr(p,axis.lower()).voltage,voltage)
    return Context().acquire(getattr(p,axis.lower()).voltage)
