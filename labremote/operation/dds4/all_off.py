from labremote.runtime.io import Context


def all_off(p):
    ctx = Context()
    for channel in range(1, 5):
        output = getattr(p, f"ch{channel}").output_enabled
        if ctx.acquire(output) != 0:
            ctx.assign(output, 0)
