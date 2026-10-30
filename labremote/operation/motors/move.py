from labremote.runtime.io import Context

def move(p, position):
    Context().assign(p.position,position)
    return Context().acquire(p.status)
