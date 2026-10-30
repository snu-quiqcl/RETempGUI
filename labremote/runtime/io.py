"""Registry-backed acquire/assign and cooperative waits for operations.

Parameter validation, readback, library updates and ownership remain in runtime.parameters.
"""
from labremote.runtime.parameters import wait
from labremote.runtime.bindings import managed_parameter


class Context:
    def acquire(self, parameter):
        managed_parameter(parameter)
        self.wait(0)
        return parameter.get()

    def assign(self, parameter, value):
        managed_parameter(parameter)
        self.wait(0)
        result = managed_parameter(parameter).assign(value)
        return result

    def wait(self, seconds):
        wait(seconds)


def acquire(parameter):
    return Context().acquire(parameter)


def assign(parameter, value):
    return Context().assign(parameter, value)
