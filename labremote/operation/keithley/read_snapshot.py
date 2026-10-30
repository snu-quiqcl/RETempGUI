from labremote.runtime.io import Context


def read_snapshot(p):
    ctx=Context()
    result={}
    result['ch1.target_voltage']=ctx.acquire(p.ch1.target_voltage)
    result['ch1.target_current']=ctx.acquire(p.ch1.target_current)
    result['ch1.voltage']=ctx.acquire(p.ch1.voltage)
    result['ch1.current']=ctx.acquire(p.ch1.current)
    result['ch1.power']=ctx.acquire(p.ch1.power)
    result['ch1.output']=ctx.acquire(p.ch1.output)
    result['ch1.voltage_limit']=ctx.acquire(p.ch1.voltage_limit)
    result['ch1.voltage_limit_state']=ctx.acquire(p.ch1.voltage_limit_state)
    result['ch2.target_voltage']=ctx.acquire(p.ch2.target_voltage)
    result['ch2.target_current']=ctx.acquire(p.ch2.target_current)
    result['ch2.voltage']=ctx.acquire(p.ch2.voltage)
    result['ch2.current']=ctx.acquire(p.ch2.current)
    result['ch2.power']=ctx.acquire(p.ch2.power)
    result['ch2.output']=ctx.acquire(p.ch2.output)
    result['ch2.voltage_limit']=ctx.acquire(p.ch2.voltage_limit)
    result['ch2.voltage_limit_state']=ctx.acquire(p.ch2.voltage_limit_state)
    result['ch3.target_voltage']=ctx.acquire(p.ch3.target_voltage)
    result['ch3.target_current']=ctx.acquire(p.ch3.target_current)
    result['ch3.voltage']=ctx.acquire(p.ch3.voltage)
    result['ch3.current']=ctx.acquire(p.ch3.current)
    result['ch3.power']=ctx.acquire(p.ch3.power)
    result['ch3.output']=ctx.acquire(p.ch3.output)
    result['ch3.voltage_limit']=ctx.acquire(p.ch3.voltage_limit)
    result['ch3.voltage_limit_state']=ctx.acquire(p.ch3.voltage_limit_state)
    return result
