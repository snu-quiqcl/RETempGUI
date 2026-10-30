from labremote.runtime.io import Context

def abort(p):
    Context().assign(p.abort,True)
