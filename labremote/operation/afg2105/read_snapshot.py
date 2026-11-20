from labremote.runtime.io import Context
from labremote.devices.afg2105.monitor import PATHS


def read_snapshot(p):
    ctx = Context()
    return {path: ctx.acquire(getattr(p,path)) for path in PATHS}
