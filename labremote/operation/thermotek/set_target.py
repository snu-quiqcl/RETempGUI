from labremote.runtime.io import Context


def set_target(p, target):
    Context().assign(p.temperature_setpoint,target)
