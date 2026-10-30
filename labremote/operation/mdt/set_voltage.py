from labremote.runtime.io import Context

def set_voltage(p, axis, value):
    if axis not in ('X','Y','Z'):raise ValueError('Select X, Y or Z')
    Context().assign(getattr(p,axis.lower()).voltage,value)
