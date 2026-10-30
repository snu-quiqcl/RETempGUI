from labremote.runtime.io import Context


def run(p):
    Context().assign(p.acquisition_command,'RUN')
