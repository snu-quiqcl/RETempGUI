from labremote.runtime.io import Context

def set_master_scan(p, enabled):
    Context().assign(p.master_scan_enabled,enabled)
