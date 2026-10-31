from labremote.runtime.io import Context

def run_sequence_file(p,request):
    ctx=Context()
    ctx.assign(p.sequence_request,request)
    return ctx.acquire(p.sequence_result)
