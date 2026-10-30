from labremote.runtime.io import Context


def dds_on(p, channel):
    ctx = Context()
    output = getattr(p, f"ch{channel}").output_enabled
    if ctx.acquire(output) == 1:
        return bool(1)
    ctx.assign(output, 1)
    return bool(1)
