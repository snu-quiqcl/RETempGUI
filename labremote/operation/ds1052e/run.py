from labremote.runtime.io import Context


def run(p):
    ctx = Context()
    ctx.assign(p.acquisition_running, True)
