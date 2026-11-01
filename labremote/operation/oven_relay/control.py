from labremote.runtime.io import Context


def open_photoionization_shutter(p, shutter):
    if shutter not in ('shutter_1','shutter_2'):raise ValueError('Invalid 399 shutter')
    Context().assign(getattr(p, shutter), 'OPEN')


def close_shutter(p, shutter):
    Context().assign(getattr(p, shutter), 'CLOSED')


def select(p, route):
    if route not in ('EA_171', 'EA_174', 'EC_171', 'EC_174'):
        raise ValueError('Select an EA/EC oven isotope route')
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
