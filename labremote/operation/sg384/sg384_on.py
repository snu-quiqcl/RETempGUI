"""sg384_on device operation."""


def sg384_on(ctx, power, output, config):
    if ctx.acquire(output):
        return True
    ctx.assign(power, config.low_power)
    ctx.assign(output, True)
    return True

