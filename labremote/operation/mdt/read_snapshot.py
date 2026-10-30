from labremote.runtime.io import Context

def read_snapshot(p):
    ctx=Context();result={}
    for path in ('output_limit_v', 'software_minimum', 'software_maximum', 'master_scan_enabled', 'x.voltage', 'x.minimum', 'x.maximum', 'y.voltage', 'y.minimum', 'y.maximum', 'z.voltage', 'z.minimum', 'z.maximum'):
        parameter=p
        for part in path.split("."):parameter=getattr(parameter,part)
        result[path]=ctx.acquire(parameter)
    return result
