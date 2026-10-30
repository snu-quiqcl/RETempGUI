from labremote.runtime.io import Context


def set_voltage_limit(p, channel, value):
    if type(channel) is not int or channel not in (1,2,3):raise ValueError('Select Keithley channel 1..3')
    ctx=Context()
    p=getattr(p,f'ch{channel}')
    ctx.assign(p.voltage_limit,value)
