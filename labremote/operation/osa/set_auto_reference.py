from labremote.runtime.io import Context

def set_auto_reference(p, enabled):
    Context().assign(p.auto_reference,enabled)
