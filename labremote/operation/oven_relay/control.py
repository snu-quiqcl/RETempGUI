from labremote.runtime.io import Context


def close_shutter(p, shutter):
    Context().assign(getattr(p, shutter), 'CLOSED')


def select(p, route):
    if route not in ('EC_171', 'EC_174'):
        raise ValueError('Only EC oven loading is enabled')
    Context().assign(p.selected_oven, route)


def open_shutter(p, shutter, route):
    ctx = Context()
    if ctx.acquire(p.selected_oven) != route:
        raise RuntimeError('Wrong oven route; shutter not opened')
    ctx.assign(getattr(p, shutter), 'OPEN')


def verify_route(p, shutter, route):
    ctx = Context()
    if ctx.acquire(p.selected_oven) != route or ctx.acquire(getattr(p, shutter)) != 'OPEN':
        raise RuntimeError('Oven route or shutter GPIO changed during loading')
