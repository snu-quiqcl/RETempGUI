from labremote.runtime.io import Context


def dds_off(p, channel):
    ctx = Context()
    output = getattr(p, f"ch{channel}").output_enabled
    if ctx.acquire(output) == 0:
        return bool(0)
    ctx.assign(output, 0)
    return bool(0)
