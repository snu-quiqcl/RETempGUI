from labremote.runtime.io import Context


def stop(p):
    ctx = Context()
    ctx.assign(p.acquisition_running, False)
