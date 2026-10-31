"""Builder only: no serial connection, upload or start at module level."""
from labremote.devices.fpga.controller import exposure_program

def build_program(parameters):
    channel=parameters.get('channel',0)
    exposure_ms=parameters.get('exposure_ms',100)
    if type(channel) is not int:raise ValueError('channel must be an integer')
    if isinstance(exposure_ms,bool) or not isinstance(exposure_ms,(int,float)):
        raise ValueError('exposure_ms must be a number')
    program,_=exposure_program(channel,exposure_ms)
    return program
