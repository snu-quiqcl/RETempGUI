from labremote.runtime.io import Context

def read_snapshot(p):return {'position':Context().acquire(p.position)}
