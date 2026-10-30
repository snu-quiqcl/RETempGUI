"""Move relative to a fresh position read, within one queued operation."""
from labremote.runtime.io import Context


def move_relative(p, distance):
    ctx = Context()
    current = ctx.acquire(p.position)
    ctx.assign(p.position, current + distance)
    return ctx.acquire(p.status)
