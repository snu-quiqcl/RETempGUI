from labremote.runtime.io import Context

def set_output(p, name, enabled):
    from labremote.devices.fpga.controller import OUTPUTS
    if name not in OUTPUTS:raise ValueError('Unknown FPGA output')
    Context().assign(getattr(p.outputs,name),enabled)
