from labremote.runtime.io import Context

def set_trace(p, name):
    Context().assign(p.trace_name,name)
