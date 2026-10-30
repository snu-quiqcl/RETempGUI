from labremote.runtime.io import Context

def read_snapshot(p):
    ctx=Context();result={}
    for path in ('states',):
        parameter=p
        for part in path.split("."):parameter=getattr(parameter,part)
        result[path]=ctx.acquire(parameter)
    return result
