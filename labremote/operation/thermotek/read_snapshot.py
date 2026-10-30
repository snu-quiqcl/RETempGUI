from labremote.runtime.io import Context


def read_snapshot(p):
    ctx=Context()
    result={}
    result['watchdog_json']=ctx.acquire(p.watchdog_json)
    result['temperature_setpoint']=ctx.acquire(p.temperature_setpoint)
    result['supply_temperature']=ctx.acquire(p.supply_temperature)
    result['ambient_temperature']=ctx.acquire(p.ambient_temperature)
    result['coolant_flow']=ctx.acquire(p.coolant_flow)
    return result
