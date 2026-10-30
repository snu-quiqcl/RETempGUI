"""Bind operation resources to acquire/assign; no value validation or execution lifecycle."""
from labremote.runtime.parameters import DeviceProxy, ManagedParameter, registry


def managed_parameter(parameter):
    if not isinstance(parameter, ManagedParameter):
        raise TypeError('Bind the parameter to the registry before using Context')
    return parameter


def bind_parameter(parameter, family, path):
    if isinstance(parameter, ManagedParameter):
        return parameter
    return ManagedParameter(parameter, ('local', id(parameter)), family, path,
                            spec=registry().get(family, path))


def bind_tree(device, family):
    if isinstance(device, DeviceProxy):
        return device
    return DeviceProxy(device, ('local', id(device)), family)


from functools import wraps
from inspect import signature

def bound_operation(*, family=None, trees=(), parameters=None):
    def decorate(function):
        sig = signature(function)
        @wraps(function)
        def run(*args, **kwargs):
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            for name in trees: bound.arguments[name] = bind_tree(bound.arguments[name], family)
            for name, path in (parameters or {}).items():
                bound.arguments[name] = bind_parameter(bound.arguments[name], family, path)
            return function(*bound.args, **bound.kwargs)
        return run
    return decorate
