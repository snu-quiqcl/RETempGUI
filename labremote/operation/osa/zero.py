from labremote.runtime.io import Context

def zero(p):
    Context().assign(p.zero_once,True)
