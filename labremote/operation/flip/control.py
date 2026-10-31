from labremote.runtime.io import Context


def move(p,position):
    if type(position) is not int or position not in (1,2):raise ValueError('Select position 1 or 2')
    Context().assign(p.position,position)
    return position
