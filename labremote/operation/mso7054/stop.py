from labremote.runtime.io import Context


def stop(p):
    Context().assign(p.acquisition_command,'STOP')
