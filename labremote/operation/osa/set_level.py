from labremote.runtime.io import Context

def set_level(p, reference, division):
    ctx=Context()
    ctx.assign(p.reference_level_dbm,reference)
    ctx.assign(p.db_per_div,division)
