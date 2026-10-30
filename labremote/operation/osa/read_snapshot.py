from labremote.runtime.io import Context

def read_snapshot(p):
    ctx=Context();result={}
    for path in ('frequency_start_thz', 'frequency_stop_thz', 'reference_level_dbm', 'db_per_div', 'auto_reference', 'trace_name'):
        parameter=p
        for part in path.split("."):parameter=getattr(parameter,part)
        result[path]=ctx.acquire(parameter)
    return result
